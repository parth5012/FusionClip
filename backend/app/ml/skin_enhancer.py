"""Face-crop skin enhancement for portraits, local engines only (#112).

Implements the engine and slider decisions locked by #111:
- Decision 1: Faithful runs GFPGAN, Creative and all five Flexible presets run
  DiffBIR. Both are Apache-2.0. CodeFormer, SUPIR, StableSR and GPEN are excluded
  on license grounds and have no loader here.
- Decision 2: `sharpen` and `smart_grain` are PIL post-filters in every mode.
  `skin_detail` is mode-aware - a texture-retention post-filter in Faithful,
  DiffBIR's guidance scale in Creative/Flexible.
- Decision 3: the five Flexible presets are a hardcoded (prompt, guidance-scale,
  condition-noise) table reachable through the pure function `get_flexible_preset`.
  No captioner: LLaVA/RAM would add ~16 GB on top of DiffBIR's 8 GB and break the
  16 GB floor from #98. Against the real DiffBIR CLI this holds: `--captioner none`
  instantiates `EmptyCaptioner`, which returns the empty string, and
  `InferenceLoop.run` joins only the non-empty parts - so `--pos_prompt` is the
  entire positive prompt. A reader who "fixes" this back to the CLI default of
  `llava` adds ~16 GB and breaks #98.
- Decision 4: face-crop only. Detect, restore each face at native resolution, paste
  back, leave the background untouched. The 512 tile engine is not reused. Max
  input dimension is capped at 8192, the same ceiling the upscaler uses.
- Decision 6: video input is refused with a named 400 reason, not ignored.
- Decision 8: on VRAM refusal or a missing GPU, the labeled degraded envelope
  (DegradedResponse) is returned at HTTP 200. Nothing here ever fabricates payload
  bytes to stand in for a result.

The two engines are wired to their *real* APIs. That is not a formality - the
first cut of this module referenced five symbols that do not exist upstream
(`FaceHelper.align_wrtk`, a `GFPGANer(face_helper=...)` kwarg,
`GFPGANer.enhance_model()`, `GFPGANer.to()`, `gfpgan.GFPGAN_VERSION_1_4`, and a
`diffusers.DiffBIRPipeline` that was never a thing), and its 64 tests stayed green
because every one of them injected a fake module that defined precisely those
symbols. tests/test_skin_engine_contracts.py now asserts the real signatures
wherever `gfpgan`/`facexlib` are importable, and denies the invented names at the
source level everywhere else.

The two engines have genuinely different shapes and the module says so rather than
pretending otherwise:

- **GFPGAN is a library.** `GFPGANer` is constructed in-process, detects, aligns,
  restores and pastes back by itself, and hands back a 3-tuple whose third element
  is a BGR ndarray. We drive it once per face crop on a PIL crop and convert at the
  boundary.
- **DiffBIR is a program.** XPixelGroup/DiffBIR is not a diffusers pipeline and is
  not on PyPI; it is a research repo whose only stable interface is
  `inference.py`'s argparse CLI, and whose config paths are CWD-relative, so it has
  to be run as a subprocess from its own root. The operator supplies the checkout
  through `DIFFBIR_REPO_PATH`. There is no importable pipeline to wrap. Because that
  process is where the models get loaded, every face crop of a request goes into one
  `--input` folder and is restored by **one** invocation - see `restore_faces` for
  why, and for what is still unmeasured about the cost of one.

Strictly guards and lazy-loads torch, gfpgan, facexlib and diffusers so the app
boots and non-GPU environments function cleanly.
"""

from __future__ import annotations

import io
import logging
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
from fastapi import HTTPException
from PIL import Image, ImageFilter
from sqlalchemy.orm import Session

from app.config import settings
from app.ml.contracts import DegradedReason, make_degraded_response
from app.ml.guard import VRAMRefusalError, vram_guard
from app.ml.registry import INFERENCE_LOCK, model_registry
from app.models import MediaAsset
from app.services.embedding import get_embedding
from app.storage import download_object, generate_url, upload_object

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Surface constants (all pure data, assertable in CI without a GPU)
# --------------------------------------------------------------------------- #

#: Magnific Skin Enhancer's three v1 modes (#111 decision 1).
SKIN_MODES: Tuple[str, ...] = ("faithful", "creative", "flexible")
DEFAULT_MODE = "faithful"

#: The mode -> engine map is the whole engine decision. Faithful is the GAN
#: (no semantic control, sub-5s per image); Creative and Flexible are the
#: diffusion refiner, because GAN restorers cannot express a prompt.
MODE_ENGINES: Dict[str, str] = {
    "faithful": "gfpgan",
    "creative": "diffbir",
    "flexible": "diffbir",
}

#: Magnific's `optimized_for` values, verbatim, unrenamed (#111 decision 3).
#: Each entry is a hardcoded (prompt, guidance-scale, condition-noise) tuple.
#: The guidance ordering is a *design choice, not a measured optimum*: it rises
#: with how far the preset departs from the source image, because DiffBIR's
#: guidance scale is what trades fidelity for "realness" (its README's word).
#: condition_noise rises alongside it so a preset can never ask for a strong
#: prompt pull with no creative headroom. All values stay <= 5.0 because past
#: that the IRControlNet visibly saturates skin texture.
FLEXIBLE_PRESETS: Dict[str, Dict[str, Any]] = {
    "enhance_skin": {
        "prompt": (
            "high quality portrait photograph of a real person, natural skin "
            "texture with visible pores, sharp detailed eyes, even lighting"
        ),
        "guidance_scale": 3.0,
        "condition_noise": 0.2,
        "description": "Smooth uneven skin and blemishes while keeping pores and natural texture",
    },
    "improve_lighting": {
        "prompt": (
            "professionally lit portrait photograph, soft balanced key light, "
            "even exposure, natural skin tone, no harsh shadows"
        ),
        "guidance_scale": 3.5,
        "condition_noise": 0.25,
        "description": "Rebuild flat or badly lit portraits with soft, even key light",
    },
    "enhance_everything": {
        "prompt": (
            "ultra detailed photograph, crisp fine detail across the whole frame, "
            "high micro contrast, sharp focus, photorealistic"
        ),
        "guidance_scale": 4.5,
        "condition_noise": 0.35,
        "description": "Push crispness and micro-contrast across the entire frame, not just skin",
    },
    "transform_to_real": {
        "prompt": (
            "photorealistic photograph of a real person, true to life skin and "
            "hair, unprocessed camera look, realistic proportions"
        ),
        "guidance_scale": 5.0,
        "condition_noise": 0.4,
        "description": "Push an illustration or render toward a real camera photograph",
    },
    "no_make_up": {
        "prompt": (
            "bare face with no makeup, natural unretouched skin, visible texture "
            "and freckles, no cosmetic filter"
        ),
        "guidance_scale": 4.0,
        "condition_noise": 0.3,
        "description": "Remove cosmetic smoothing and filters, back to unretouched skin",
    },
}

DEFAULT_FLEXIBLE_PRESET = "enhance_skin"

#: Creative mode has no preset to inherit a guidance scale from, so it carries one
#: of its own. 3.5 is a *design choice inside DiffBIR's real range*, not a
#: transcription: `--cfg_scale` defaults to 6.0 on the CLI and to 8 in upstream's
#: webui (slider range 1..10, step 1). Those defaults are tuned for whole-image
#: blind super-resolution, where a strong prompt pull is wanted; a face crop that
#: must keep the subject's identity is a different job, and #111's five presets
#: all sit in the 3.0-5.0 band for the same reason. Unverified without a GPU.
CREATIVE_PROMPT = (
    "high quality portrait photograph of a real person, detailed natural skin, "
    "sharp eyes, photorealistic"
)
CREATIVE_BASE_GUIDANCE = 3.5
#: Creative mode also has no preset for condition noise, so it takes a fixed
#: mid-range value: enough headroom for a single unguided prompt, well below the
#: most creative Flexible preset.
CREATIVE_CONDITION_NOISE = 0.25

#: DiffBIR v2.1 ships 10-step samplers (per its release notes) and #111 states a
#: ~60s-per-image design target for Creative/Flexible, so 10 steps is the setting that
#: fits *within* that target on paper. Chosen, not measured: no DiffBIR run has been
#: timed in this repo, so nothing here establishes that any configuration lands under
#: 60s. Treat the figure as the budget the engine was picked against, not as a
#: benchmark result.
DIFFBIR_INFERENCE_STEPS = 10

# --------------------------------------------------------------------------- #
# DiffBIR real-CLI surface (XPixelGroup/DiffBIR, Apache-2.0, commit 5c2d6c1)
#
# Every value below is transcribed from `inference.py::parse_args` and the loop
# classes it dispatches to. DiffBIR is not importable as a library, so its
# argparse surface *is* its API, and the only way to be wrong about it is to
# guess - so nothing here is guessed, and the argv is asserted in CI by
# tests/test_skin_engine_contracts.py.
# --------------------------------------------------------------------------- #

#: `--task unaligned_face` -> `UnAlignedBFRInferenceLoop`, which is the loop that
#: takes already-cropped / arbitrarily-oriented faces. It runs its own face
#: detector over whatever we stage, so a staged crop is a legitimate input.
#: `--version v2.1` because v1 explicitly refuses unaligned BFR
#: (`UnAlignedBFRInferenceLoop.load_cleaner` raises for v1).
DIFFBIR_TASK = "unaligned_face"
DIFFBIR_VERSION = "v2.1"
#: Seed 231 is upstream's own default, so a Creative run is reproducible rather
#: than different on every request. (Determinism matters here: `smart_grain` is
#: already seeded for the same reason.)
DIFFBIR_SEED = 231
DIFFBIR_DEVICE = "cuda"
DIFFBIR_PRECISION = "fp16"
#: `--upscale 1`. Upstream's default is 4, which would hand us a face crop four
#: times larger than the box we are pasting back into. At 1 the composed
#: `<stem>_0.png` comes out at the staged crop's own resolution.
DIFFBIR_UPSCALE = 1

#: `--noise_aug` is `type=int` and is fed straight into
#: `diffusion.q_sample(t=noise_aug)`, where 0 means "no condition noise at all"
#: (the pipeline short-circuits on `if noise_aug > 0`). 199 is the top of the
#: range in upstream's own gradio webui. #111's preset column is a 0..1
#: creativity fraction written against a *diffusers* 0..100 knob that never
#: existed, so it is rescaled linearly onto these endpoints.
#:
#: Honest caveat: the endpoints are upstream's own; where each preset lands
#: *inside* the range is a linear rescale chosen by us and is UNVERIFIED without
#: a GPU. Re-tune this constant against real output before treating the presets'
#: relative ordering as meaningful.
DIFFBIR_MAX_NOISE_AUG = 199

#: DiffBIR's own `DEFAULT_NEG_PROMPT`, copied verbatim from `inference.py`.
#: Copied rather than invented because it happens to be right for a portrait
#: enhancer: it penalises "over-smooth" (exactly what the `no_make_up` preset
#: asks to remove) and "painting, illustration, drawing, art, sketch, ...
#: 3D render, unreal engine" (exactly what `transform_to_real` pushes away
#: from). Anything we wrote here would be a guess with no evidence behind it.
DIFFBIR_NEGATIVE_PROMPT = (
    "painting, oil painting, illustration, drawing, art, sketch, oil painting, cartoon, "
    "CG Style, 3D render, unreal engine, blurring, dirty, messy, worst quality, low quality, "
    "frames, watermark, signature, jpeg artifacts, deformed, lowres, over-smooth."
)


#: Sliders are unipolar Magnific-native 0..100 integers (#111 decision 4). The
#: upscaler's -10..+10 bipolar convention is untouched and deliberately not
#: reused here: half of that range would be meaningless for these knobs.
SLIDER_MIN = 0
SLIDER_MAX = 100

#: Magnific's documented default for `skin_detail` (#111 decision 4).
DEFAULT_SKIN_DETAIL = 80

#: Max input dimension, the same ceiling the upscaler clamps to. A 12000px phone
#: export is legitimate input, so it is rescaled rather than refused; only face
#: crops are actually re-rendered, so the background pixels we drop are never
#: looked at.
MAX_INPUT_DIMENSION = 8192

#: Below this a detected box has no usable facial landmarks to align against, so
#: a restore attempt on it is guaranteed noise. Such boxes are dropped, and if
#: that empties the list the request is refused as no-face rather than run.
MIN_FACE_DIMENSION = 32

#: Output object-key prefix and the source/lineage contract (#111 decision 7).
OUTPUT_PREFIX = "skin_enhanced"

#: Video extensions we refuse by name. The MediaAsset content_type is checked
#: first; this list is the fallback for a key with no catalog row, because the
#: user must be told either way (#111 decision 6).
VIDEO_CONTENT_PREFIXES = ("video/",)
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi", ".mpg", ".mpeg", ".wmv", ".flv"}
)

# --- post-filter tunables, every one commented with its reason ---------------

#: PIL's UnsharpMask `percent` is an unbounded exaggeration of the
#: (image - blurred) difference. 200 is a strong but stable edge crispening on a
#: 512px face crop; 500 starts producing visible halos on skin texture. The
#: upscaler uses the same 1.2 radius and 3 threshold, so the two post-filters do
#: not disagree about what "sharp" means.
MAX_UNSHARP_PERCENT = 200
UNSHARP_RADIUS = 1.2
#: 3/255 is the noise floor under which sharpening amplifies sensor noise rather
#: than detail; matching the upscaler's threshold keeps behaviour consistent.
UNSHARP_THRESHOLD = 3

#: Film grain is a zero-mean perturbation. sigma 6 levels is ~2.4% of full
#: scale: clearly visible on smooth skin (the plastic-smoothing look Magnific's
#: `smart_grain` exists to prevent) without reading as sensor noise.
MAX_GRAIN_SIGMA = 6.0
#: Fixed seed so the same request is byte-reproducible. Grain that differs run to
#: run would make a before/after diff meaningless and would make CI flaky.
GRAIN_SEED = 0

#: Radius of the Gaussian used to split an image into its low and high
#: frequencies for texture retention. 2.0 px is the size of the micro-texture
#: GFPGAN smooths away (pores, fine hair), not the scale of facial features.
TEXTURE_RADIUS = 2.0

#: Working-set headroom reserved on top of the model's registry footprint while
#: a face crop is resident. Same 1.0 GB the image and audio executors use.
WORKING_OVERHEAD_GB = 1.0

FaceBox = Tuple[int, int, int, int]

# --------------------------------------------------------------------------- #
# GFPGAN / facexlib real-API surface (gfpgan 1.3.8, facexlib 0.3.0)
# --------------------------------------------------------------------------- #

#: `GFPGANer.__init__(model_path, upscale=2, arch='clean', channel_multiplier=2,
#: bg_upsampler=None, device=None)`. Note what is *not* there: no `face_helper=`
#: kwarg, no `enhance_model()` method, no `.to()`. The helper is built internally
#: and the device is a constructor argument.
#:
#: `GFPGAN_ARCH`/`GFPGAN_ARCH_CHANNEL_MULTIPLIER` must match the checkpoint or
#: `load_state_dict(strict=True)` raises on the first load. 'clean' is
#: `GFPGANv1Clean`; the weights below are the matching v1.2 clean release asset
#: ("no colorization, no CUDA extensions", per the GFPGAN model zoo). Upstream
#: pairs exactly these two values in its own `inference_gfpgan.py` for version
#: 1.2, so this pair is transcribed, not chosen.
GFPGAN_ARCH = "clean"
GFPGAN_ARCH_CHANNEL_MULTIPLIER = 2
#: Official release asset for that checkpoint. `GFPGANer.__init__` special-cases
#: an `https://` model_path and downloads it through basicsr's
#: `load_file_from_url`, so this works with no bundled checkpoint and no operator
#: setup. Overridable with `GFPGAN_MODEL_PATH` for air-gapped hosts.
#: gfpgan exports *no* `GFPGAN_VERSION_*` constants - the first cut of this module
#: imported `GFPGAN_VERSION_1_4` and would have died with ImportError.
GFPGAN_MODEL_URL = (
    "https://github.com/TencentARC/GFPGAN/releases/download/v0.2.0/"
    "GFPGANCleanv1-NoCE-C2.pth"
)
#: `upscale=1`: restore at native resolution, no model upscale. Combined with
#: `bg_upsampler=None` this is what implements #111 decision 4's "background
#: untouched" - `GFPGANer.enhance` pastes the restored faces into
#: `cv2.resize(input_img, (w, h))` at factor 1, i.e. into a copy of its own input.
GFPGAN_UPSCALE = 1
#: gfpgan 1.3.8 exports only this class. Nothing else is needed: the detector,
#: the face template, the 512 alignment and the paste-back all live inside it.
#: Importing `facexlib.face_helper.FaceHelper` (the older S3FD-era helper) is what
#: the first cut did, and that class does not exist in facexlib 0.3.0.
GFPGAN_CLASS = "GFPGANer"

#: facexlib 0.3.0's `init_detection_model` implements exactly two detectors -
#: `retinaface_resnet50` and `retinaface_mobile0.25` - and raises
#: `NotImplementedError` for anything else, `s3fd` included. There is no
#: `detection_model=` argument anywhere: the choice is `det_model=`.
#:
#: We use `retinaface_resnet50` for both tiers, and that is a deliberate choice
#: rather than an oversight. `GFPGANer` hardcodes `retinaface_resnet50` for the
#: helper it builds, and offers no supported way to change it - the only lever
#: would be assigning over `restorer.face_helper` after construction, which means
#: re-deriving the `face_size` / `crop_ratio` / `upscale_factor` / `use_parse`
#: wiring that `enhance()` depends on for its paste-back geometry. Meanwhile
#: DiffBIR's own `UnAlignedBFRInferenceLoop.setup()` also uses
#: `retinaface_resnet50`. Agreeing with both is worth more here than the ~50 MB
#: `retinaface_mobile0.25` would save, because a detector disagreement shows up
#: as "we cropped a box DiffBIR does not think is a face".
DETECT_MODEL = "retinaface_resnet50"


# --------------------------------------------------------------------------- #
# Pure functions: the parameter mapping and the preset table
# --------------------------------------------------------------------------- #


def get_flexible_preset(name: Optional[str]) -> Dict[str, Any]:
    """Return a Flexible preset tuple, or raise naming the allowed set.

    Pure by construction - a static dict lookup with no I/O, no registry access
    and no GPU - which is what makes the table assertable in CI (#111 decision 3).
    """
    key = name or DEFAULT_FLEXIBLE_PRESET
    preset = FLEXIBLE_PRESETS.get(key)
    if preset is None:
        raise ValueError(
            f"Unknown Flexible preset '{name}'. "
            f"Allowed presets: {', '.join(sorted(FLEXIBLE_PRESETS))}"
        )
    return preset


def map_skin_detail_to_guidance(skin_detail: int, base_guidance: float) -> float:
    """Map the 0..100 `skin_detail` slider onto DiffBIR's guidance scale.

    Anchored so the default slider position (80) reproduces `base_guidance`
    exactly - the preset's own guidance column would otherwise be dead weight.
    0 is the "off" end and floors at 1.0, DiffBIR's effective no-prompt-pull
    value; that floor is a property of the model, not a silent clamp of the
    caller's input, which is range-checked and refused with a 400 instead.
    """
    return round(max(1.0, float(base_guidance) * (skin_detail / DEFAULT_SKIN_DETAIL)), 3)


def map_skin_detail_to_texture_retention(skin_detail: int) -> float:
    """Map the 0..100 `skin_detail` slider onto a Faithful-mode high-pass weight.

    Higher means more retained skin texture, which is the direction Magnific
    documents for the Faithful slider. 0 means "leave the GAN output alone".
    """
    return round(skin_detail / 100.0, 3)


def map_sharpen_to_percent(sharpen: int) -> int:
    """Map 0..100 onto PIL's UnsharpMask percent (PIL takes an int here)."""
    return int(round(sharpen / SLIDER_MAX * MAX_UNSHARP_PERCENT))


def map_smart_grain_to_sigma(smart_grain: int) -> float:
    """Map 0..100 onto a zero-mean Gaussian grain sigma in 8-bit levels."""
    return round(smart_grain / SLIDER_MAX * MAX_GRAIN_SIGMA, 3)


def map_condition_noise_to_noise_aug(condition_noise: float) -> int:
    """Map #111's 0..1 `condition_noise` onto DiffBIR's integer `--noise_aug`.

    `--noise_aug` is `type=int` and is used as a diffusion timestep:
    `diffusion.q_sample(x_start=cond["c_img"], t=noise_aug)`, gated on
    `if noise_aug > 0`. 0 therefore has to survive the mapping as 0 - it is
    DiffBIR's own "off" value, not a clamp. The top of the range is 199, the
    maximum of the slider in upstream's gradio webui.

    See `DIFFBIR_MAX_NOISE_AUG` for the honest caveat: the endpoints are
    upstream's, the placement of each preset between them is a linear rescale we
    chose and have not seen output from.
    """
    fraction = min(1.0, max(0.0, float(condition_noise)))
    return int(round(fraction * DIFFBIR_MAX_NOISE_AUG))



def resolve_engine_params(
    mode: str, preset: Optional[str], skin_detail: int
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Resolve (engine_id, restore kwargs) for a mode/preset/slider combination.

    Faithful resolves to an *empty* kwargs dict on purpose: GFPGAN has no
    semantic control, so forwarding a prompt or a guidance scale would mean the
    mode silently stopped being Faithful. The pure post-filters are applied
    afterwards, outside the engine, in every mode.
    """
    if mode == "faithful":
        return MODE_ENGINES[mode], None
    if mode == "flexible":
        chosen = get_flexible_preset(preset)
        return MODE_ENGINES[mode], {
            "prompt": chosen["prompt"],
            "guidance_scale": map_skin_detail_to_guidance(
                skin_detail, chosen["guidance_scale"]
            ),
            "condition_noise": float(chosen["condition_noise"]),
            "num_inference_steps": DIFFBIR_INFERENCE_STEPS,
        }
    return MODE_ENGINES[mode], {
        "prompt": CREATIVE_PROMPT,
        "guidance_scale": map_skin_detail_to_guidance(skin_detail, CREATIVE_BASE_GUIDANCE),
        "condition_noise": CREATIVE_CONDITION_NOISE,
        "num_inference_steps": DIFFBIR_INFERENCE_STEPS,
    }


# --------------------------------------------------------------------------- #
# Pure functions: the PIL post-filters
# --------------------------------------------------------------------------- #


def apply_skin_post_filters(
    image: Image.Image, sharpen: int, smart_grain: int
) -> Image.Image:
    """Apply `sharpen` then `smart_grain`. Both are 0..100 and unipolar.

    At 0 each filter is skipped outright rather than run with a neutral
    argument, so "off" means the pixels come back bit-identical instead of
    merely close.
    """
    result = image

    percent = map_sharpen_to_percent(sharpen)
    if percent > 0.0:
        result = result.filter(
            ImageFilter.UnsharpMask(
                radius=UNSHARP_RADIUS, percent=percent, threshold=UNSHARP_THRESHOLD
            )
        )

    sigma = map_smart_grain_to_sigma(smart_grain)
    if sigma > 0.0:
        arr = np.asarray(result, dtype=np.float32)
        rng = np.random.default_rng(GRAIN_SEED)
        grain = rng.normal(0.0, sigma, size=arr.shape).astype(np.float32)
        # fromarray infers the mode from the (H, W, 3) uint8 shape, so no explicit
        # mode= is passed: that argument is deprecated in Pillow 10+.
        result = Image.fromarray(np.clip(arr + grain, 0.0, 255.0).astype(np.uint8))

    return result


def apply_texture_retention(
    source: Image.Image, restored: Image.Image, strength: float
) -> Image.Image:
    """Re-inject the *source's* high-frequency micro-texture at `strength` (0.0 .. 1.0).

    Faithful-mode `skin_detail` is exactly this: GFPGAN's generative prior
    reconstructs a *plausible* face, which means it averages away pores and fine
    hair. That detail only exists in the source crop - a local unsharp of the
    restored crop cannot recreate it, it just exaggerates whatever ringing the GAN
    left behind. So the high-pass band is computed from `source` and added to
    `restored`; nothing is invented, and at 0.0 the restored crop is returned
    unchanged.

    The two crops must be the same region of the same image (the caller passes the
    face box twice, once from the source and once from the restored composite).
    """
    if strength <= 0.0:
        return restored
    src = np.asarray(source, dtype=np.float32)
    low = np.asarray(
        source.filter(ImageFilter.GaussianBlur(radius=TEXTURE_RADIUS)), dtype=np.float32
    )
    high = src - low
    base = np.asarray(restored, dtype=np.float32)
    return Image.fromarray(np.clip(base + high * float(strength), 0.0, 255.0).astype(np.uint8))


# --------------------------------------------------------------------------- #
# Engine adapters. Heavy imports stay inside the loader closures.
# --------------------------------------------------------------------------- #


def pil_to_bgr(image: Image.Image) -> np.ndarray:
    """PIL RGB -> the BGR `np.uint8` ndarray both engines actually take.

    `FaceRestoreHelper.read_image` documents its input as "Numpy array, (h, w, c),
    BGR, uint8" and `GFPGANer.enhance` passes straight through to it, so a PIL
    image handed over unconverted is not a type error the upstream code catches -
    it is a `len(img.shape)` failure several frames later, or worse, a silently
    red/blue-swapped restoration.

    The `.copy()` is load-bearing, not defensive: `arr[:, :, ::-1]` is a
    negative-stride *view*, and both `Image.fromarray` and every cv2 function
    reject one.
    """
    return np.asarray(image.convert("RGB"), dtype=np.uint8)[:, :, ::-1].copy()


def bgr_to_pil(array: np.ndarray) -> Image.Image:
    """The inverse of `pil_to_bgr`. Same contiguity requirement, same reason."""
    array = np.asarray(array)
    if array.ndim == 2:
        array = np.stack([array] * 3, axis=-1)
    if array.ndim != 3 or array.shape[2] < 3:
        raise ValueError(
            f"Unrecognized engine output shape {array.shape}; expected (h, w, 3) BGR"
        )
    return Image.fromarray(array[:, :, :3][:, :, ::-1].copy()).convert("RGB")


def _boxes_from_det_faces(det_faces: Optional[Sequence[Any]]) -> List[FaceBox]:
    """Normalise facexlib's `det_faces` rows into integer boxes.

    Real `det_faces` entries are numpy rows of `[x0, y0, x1, y1, score]` in the
    coordinate space of the image that was read (float, and routinely a few pixels
    outside the frame). Rows with fewer than 4 elements are skipped rather than
    raising: a detector version that returns a different tuple shape is a
    condition the caller must be able to survive, not crash on.
    """
    boxes: List[FaceBox] = []
    for row in det_faces or []:
        values = list(np.asarray(row).reshape(-1))
        if len(values) < 4:
            continue
        boxes.append(tuple(int(v) for v in values[:4]))  # type: ignore[arg-type]
    return boxes


class GFPGANFaceEngine:
    """Adapter over the real `GFPGANer`, one face crop in and one crop out.

    `GFPGANer` is not a low-level model wrapper - it builds its own
    `FaceRestoreHelper`, then `enhance()` does the whole job: `clean_all()`,
    `read_image()`, `get_face_landmarks_5()`, `align_warp_face()`, one forward
    pass per aligned crop, `get_inverse_affine()` and
    `paste_faces_to_input_image()`. The first cut of this class tried to
    reimplement that loop by hand, which is both how you end up holding a broken
    `face_helper` and how you end up reimplementing gfpgan's tensor plumbing
    (`img2tensor` / `normalize` / `tensor2img`) badly. So it is not reimplemented:
    `enhance(paste_back=True)` is called and its third return value is used.

    Two ordering constraints from the route are preserved:

    * **Detect before you spend a forward pass.** `detect_faces` runs the real
      helper's own detect step (`read_image` + `get_face_landmarks_5`) and reads
      `det_faces`, so a picture with no face still answers `no_face_detected`
      without ever constructing the generator's output.
    * **One crop at a time.** The executor crops a box and hands it over, so the
      executor keeps control of the crop/paste-back loop and every pixel outside
      the boxes provably cannot be touched (#111 decision 4).

    There is deliberately no `restore_faces` here, and the executor's batch branch
    keys off that method, so the omission is load-bearing rather than an oversight.
    Two reasons. First, batching only pays when the per-call cost is dominated by
    setup: GFPGAN's model is resident in this process for the request (`model_registry`
    caches the loaded instance), so its Nth face is one forward pass on weights that
    are already there. Second, `enhance()` re-detects faces *inside* the image it is
    given, so handing it N crops as one image is a different operation, not a batched
    one - it would change what Faithful mode does. DiffBIR has the opposite shape
    (a subprocess per call that reloads everything) and does get a batch entry point.
    """

    def __init__(self, restorer: Any):
        # `restorer.face_helper` is the `FaceRestoreHelper` GFPGANer built for
        # itself. Reusing it is deliberate: it is the only helper whose
        # face_size / crop_ratio / upscale_factor / use_parse wiring is known to
        # agree with what `enhance()` does at paste-back time.
        self.restorer = restorer

    @property
    def face_helper(self) -> Any:
        """The restorer's own helper. Not injected, not shared with another engine."""
        return self.restorer.face_helper

    def detect_faces(self, image: Image.Image) -> List[FaceBox]:
        helper = self.face_helper
        # `clean_all()` first: `get_face_landmarks_5` *appends* to `det_faces`,
        # so without this a second request would see the first one's faces too.
        helper.clean_all()
        helper.read_image(pil_to_bgr(image))
        # `eye_dist_threshold=5` matches what GFPGANer.enhance itself uses, so the
        # boxes we report here are the same set the restore pass will act on.
        helper.get_face_landmarks_5(only_center_face=False, eye_dist_threshold=5)
        return _boxes_from_det_faces(getattr(helper, "det_faces", None))

    def restore_face(self, crop: Image.Image, **params: Any) -> Image.Image:
        if params:
            raise ValueError(
                "Faithful mode's engine (GFPGAN) has no prompt or guidance control; "
                f"unexpected parameters forwarded: {sorted(params)}"
            )
        # `enhance` re-detects inside the crop, which is what we want: the crop is
        # a tight box, and a second detection there is far cheaper than
        # reimplementing align/restore/paste for a single box.
        result = self.restorer.enhance(
            pil_to_bgr(crop),
            has_aligned=False,
            only_center_face=False,
            paste_back=True,
        )
        # The real return is the 3-tuple (cropped_faces, restored_faces,
        # restored_img). The first cut checked `isinstance(restored, Image.Image)`
        # on the *tuple* and raised "Unrecognized GFPGAN output type: tuple" on
        # every single Faithful request.
        if not isinstance(result, tuple) or len(result) != 3:
            raise ValueError(
                "GFPGANer.enhance did not return the documented "
                f"(cropped_faces, restored_faces, restored_img) 3-tuple, got "
                f"{type(result).__name__}"
            )
        cropped_faces, _restored_faces, restored_img = result
        if not cropped_faces:
            # `enhance` re-detects inside the crop we hand it. If that detection
            # comes back empty - a box that was clamped into the canvas until the
            # face was mostly out of frame, say - it still returns a 3-tuple whose
            # third element is the input crop, unchanged. Returning that would tell
            # the caller a face was restored when nothing was, so it is an error.
            raise ValueError(
                "GFPGANer.enhance found no face inside the crop it was given, so it "
                "restored nothing and its pasted-back image is the input unchanged. "
                "Refusing to report that as a restoration."
            )
        if restored_img is None:
            # `enhance` returns None for the third element when
            # `has_aligned or not paste_back`; we ask for neither, so a None here
            # means the call did not do what was asked and returning the input
            # crop would be a lie about it having been restored.
            raise ValueError(
                "GFPGANer.enhance(paste_back=True) returned no pasted-back image; "
                "the input crop was not restored"
            )
        return bgr_to_pil(restored_img)


def build_diffbir_argv(
    python_executable: str,
    repo_root: Path,
    input_dir: Path,
    output_dir: Path,
    *,
    prompt: str,
    guidance_scale: float,
    condition_noise: float,
    negative_prompt: str = DIFFBIR_NEGATIVE_PROMPT,
    steps: int = DIFFBIR_INFERENCE_STEPS,
    device: str = DIFFBIR_DEVICE,
    precision: str = DIFFBIR_PRECISION,
    seed: int = DIFFBIR_SEED,
) -> List[str]:
    """Build the argv for one DiffBIR invocation. Pure, so CI can assert on it.

    Every flag here exists in `inference.py::parse_args`; none of them is a diffusers
    pipeline keyword. Two spellings are load-bearing and easy to get wrong:

    * `--cleaner_tiled` and `--cldm_tiled` are `action="store_true"`. Writing
      `--cleaner_tiled true` makes argparse treat `true` as an unrecognised
      positional and abort, *after* loading five models.
    * `--input` and `--output` are **folders**, not files. `InferenceLoop.load_lq`
      walks `sorted(os.listdir(args.input))` and keeps `.png/.jpg/.jpeg`.

    `--captioner none` is the load-bearing one for this project: see the module
    docstring. It is the CLI default of `llava` that would cost ~16 GB (#111).
    """
    return [
        python_executable,
        str(Path(repo_root) / "inference.py"),
        "--input",
        str(input_dir),
        "--output",
        str(output_dir),
        "--task",
        DIFFBIR_TASK,
        "--version",
        DIFFBIR_VERSION,
        "--upscale",
        str(DIFFBIR_UPSCALE),
        "--captioner",
        "none",
        "--pos_prompt",
        prompt,
        "--neg_prompt",
        negative_prompt,
        "--cfg_scale",
        str(round(float(guidance_scale), 4)),
        "--noise_aug",
        str(map_condition_noise_to_noise_aug(condition_noise)),
        "--steps",
        str(int(steps)),
        # Bare `store_true` flags, no "true" token. DiffBIR's published 8 GB figure
        # is *for tiled inference*; without these two the registry number is wrong.
        "--cleaner_tiled",
        "--cldm_tiled",
        "--device",
        device,
        "--precision",
        precision,
        "--seed",
        str(int(seed)),
        "--n_samples",
        "1",
    ]


def resolve_diffbir_repo_path() -> Path:
    """Locate the operator-supplied DiffBIR checkout, or raise naming what is wrong.

    XPixelGroup/DiffBIR is not on PyPI (it is a research repo with a `guided_diffusion`
    submodule), so `pip install diffbir` cannot be used to make Creative/Flexible work.
    The operator clones it and points `DIFFBIR_REPO_PATH` at the repo root - the
    directory containing `inference.py` and `configs/`, which is also the directory
    the subprocess has to run *in*, because `inference.py` loads its configs with the
    CWD-relative `OmegaConf.load("configs/inference/swinir.yaml")`.

    Raising here (rather than degrading later) is deliberate: the executor turns any
    loader exception into the labeled LOAD_FAILED envelope with this message, so the
    operator is told exactly which setting to fix, and no output is ever invented.
    """
    raw = (settings.DIFFBIR_REPO_PATH or "").strip()
    if not raw:
        raise ValueError(
            "DIFFBIR_REPO_PATH is not configured. XPixelGroup/DiffBIR is not "
            "installable from PyPI, so Creative and Flexible modes need a local "
            "checkout: `git clone --recursive https://github.com/XPixelGroup/DiffBIR` "
            "and set DIFFBIR_REPO_PATH to that directory (the one holding "
            "inference.py and configs/). Faithful mode does not need it."
        )
    repo_root = Path(raw).expanduser()
    if not repo_root.is_dir():
        raise ValueError(
            f"DIFFBIR_REPO_PATH={raw!r} is not a directory. Set it to the root of a "
            "DiffBIR checkout - the directory containing inference.py and configs/."
        )
    entrypoint = repo_root / "inference.py"
    if not entrypoint.is_file():
        raise ValueError(
            f"DIFFBIR_REPO_PATH={raw!r} has no inference.py at its root, so it is not "
            "a DiffBIR checkout. Set it to the repository root, not to a subdirectory."
        )
    return repo_root


class DiffBIRFaceEngine:
    """Adapter that drives DiffBIR's CLI - every face crop in one invocation.

    There is no importable DiffBIR pipeline to wrap - see the module docstring. This
    class therefore does three things and delegates the rest:

    1. Detects faces with its own `FaceRestoreHelper`, so the route's
       `no_face_detected` refusal, its out-of-canvas clamping and its reported
       `face_boxes` all still work. (DiffBIR's loop detects too, but only over
       whatever we stage, i.e. after the refusal decision has already been made.)
    2. Writes every crop to ONE staging directory as a real PNG, because `--input` is
       a folder and upstream's `load_lq` globs it with
       `sorted(os.listdir(...))`, keeping `.png/.jpg/.jpeg`.
    3. Reads `<stem>_0.png` back out of `--output`, one per staged crop.

    The output name is `<stem>_0.png`, not `<stem>.png`, and that is worth being
    precise about: `UnAlignedBFRInferenceLoop.save` is an override, and it writes the
    *composed* image as `f"{file_stem}_{i}.png"` (with `n_samples=1`, so `_0`).
    The plain `<stem>.png` form is the base `InferenceLoop.save` and is only used by
    the `sr`/`denoise` tasks. It also drops the per-face samples in
    `restored_faces/` and the input crops in `cropped_faces/`; we read the composed
    one, which is already the crop with the restored face pasted back at
    `--upscale 1`.

    Why one invocation for the whole request: a DiffBIR invocation is a *process*, and
    the process is what loads the models. Each run loads SwinIR (x2), ControlLDM, SD
    2.1 and the diffusion schedule, so the first cut - one `restore_face` call per
    detected face - made a 6-face group shot pay the whole load six times over. Since
    `--input` is a folder, that was never a requirement, only an accident of the
    executor's loop. `restore_faces` stages all the crops and shells out once.

    Honest position on cost, since it is easy to overstate: batching amortises the
    model load across the faces of *one* request - the N-fold load multiplier is gone
    - but it does not make a request cheap, and **no wall-clock number for
    Creative/Flexible has ever been measured here, because there is no GPU in CI**.
    The ~60s per image in #111 is a design target the engine was chosen against, not
    a benchmark and not a verified bound. Do not read "one process now" as "within
    budget"; only a real DiffBIR checkout on a real GPU can say that.
    """

    def __init__(
        self,
        repo_path: str,
        python_executable: str,
        timeout_seconds: float,
        device: str = DIFFBIR_DEVICE,
        precision: str = DIFFBIR_PRECISION,
    ):
        self.repo_root = resolve_diffbir_repo_path() if not repo_path else Path(repo_path)
        # `DIFFBIR_PYTHON` exists because DiffBIR pins `torch==2.2.2+cu118` +
        # `xformers==0.0.25.post1+cu118`, which in practice does not coexist with
        # this app's own torch. Defaulting to our interpreter is correct only when
        # someone has installed DiffBIR's deps alongside ours.
        self.python_executable = python_executable or sys.executable
        self.timeout_seconds = float(timeout_seconds)
        self.device = device
        self.precision = precision
        self._face_helper: Any = None

    def _build_face_helper(self) -> Any:
        if self._face_helper is None:
            import torch  # type: ignore
            from facexlib.utils.face_restoration_helper import (  # type: ignore
                FaceRestoreHelper,
            )

            # Mirrors the configuration DiffBIR's own UnAlignedBFRInferenceLoop
            # builds, so the boxes this adapter reports and the crops DiffBIR
            # decides are faces cannot disagree. `upscale_factor=1` because we paste
            # back into the source box at native resolution.
            self._face_helper = FaceRestoreHelper(
                1,
                face_size=512,
                crop_ratio=(1, 1),
                det_model=DETECT_MODEL,
                save_ext="png",
                use_parse=False,
                device=torch.device(
                    "cuda" if (self.device == "cuda" and torch.cuda.is_available()) else "cpu"
                ),
            )
        return self._face_helper

    def detect_faces(self, image: Image.Image) -> List[FaceBox]:
        # No torch import here: the helper is built lazily on the first call, and
        # after that detection needs only the mirror/real helper's numpy plumbing.
        helper = self._build_face_helper()
        helper.clean_all()
        helper.read_image(pil_to_bgr(image))
        helper.get_face_landmarks_5(only_center_face=False, eye_dist_threshold=5)
        return _boxes_from_det_faces(getattr(helper, "det_faces", None))

    @staticmethod
    def _validate_restore_params(params: Dict[str, Any]) -> None:
        """DiffBIR's argv is built from exactly these four values and nothing else.

        Checked rather than defaulted, because a missing key here means
        `resolve_engine_params` failed to do its job for this mode, and silently
        substituting a default would turn a mapping bug into a plausible-looking
        render nobody could explain.
        """
        missing = [
            key
            for key in ("prompt", "guidance_scale", "condition_noise", "num_inference_steps")
            if key not in params
        ]
        if missing:
            raise ValueError(
                f"DiffBIR needs {sorted(missing)} to build its argv; the Creative and "
                "Flexible parameter mapping in resolve_engine_params should have "
                "supplied them"
            )
        unexpected = set(params) - {
            "prompt",
            "guidance_scale",
            "condition_noise",
            "num_inference_steps",
        }
        if unexpected:
            raise ValueError(f"Unexpected DiffBIR parameters forwarded: {sorted(unexpected)}")

    def restore_faces(
        self, crops: Sequence[Image.Image], **params: Any
    ) -> List[Image.Image]:
        """Restore every crop with ONE subprocess, and return them in the given order.

        The staging layout is the whole contract with upstream: `--input` is globbed
        with `sorted(os.listdir(...))` and `save()` writes `<stem>_0.png` per input, so
        the crops are staged as `<run token>_<index>.png` and read back by the same
        stem. The index is zero-padded so the sorted order upstream sees is the order
        the crops were given in - it does not have to be, because the read-back is by
        name, but a `sorted()` that scrambled them would make any future debugging of
        the output directory actively misleading.

        Every crop is a face crop from a detected box and nothing else (#111 decision
        4): the executor hands this method crops, never the image, so no background
        pixel can reach DiffBIR even transitively through the staging directory.

        All-or-nothing: if even one `<stem>_0.png` is missing the whole call raises. A
        short list would be worse than an error here, because the executor pairs
        results with boxes *positionally* - a list missing its first entry would paste
        face 2's restoration onto face 1's box and report success.
        """
        self._validate_restore_params(params)
        crop_list = list(crops)
        if not crop_list:
            # Nothing to restore, so nothing to launch. DiffBIR would happily start,
            # load five models and write no output.
            return []

        # A uuid run token, because a fixed stem would collide with a stale file if the
        # staging directory were ever reused. The directory is fresh regardless, but
        # the name is free and this removes the question.
        run = uuid.uuid4().hex[:12]
        stems = [f"face_{run}_{index:04d}" for index in range(len(crop_list))]
        with tempfile.TemporaryDirectory(prefix="fusionclip-diffbir-") as workdir:
            input_dir = Path(workdir) / "in"
            output_dir = Path(workdir) / "out"
            # Created up front: `load_lq` asserts `os.path.isdir(args.input)` and
            # `setup()` only creates the *output* side.
            input_dir.mkdir()
            output_dir.mkdir()
            for stem, crop in zip(stems, crop_list):
                crop.convert("RGB").save(input_dir / f"{stem}.png", format="PNG")

            argv = build_diffbir_argv(
                python_executable=self.python_executable,
                repo_root=self.repo_root,
                input_dir=input_dir,
                output_dir=output_dir,
                prompt=str(params["prompt"]),
                guidance_scale=float(params["guidance_scale"]),
                condition_noise=float(params["condition_noise"]),
                steps=int(params["num_inference_steps"]),
                device=self.device,
                precision=self.precision,
            )

            logger.info(
                f"Skin enhance: running DiffBIR once for {len(stems)} face crop(s) in "
                f"{input_dir} (task={DIFFBIR_TASK}, version={DIFFBIR_VERSION})"
            )
            try:
                completed = subprocess.run(  # noqa: S603 - argv is built here, not caller-supplied
                    argv,
                    cwd=str(self.repo_root),
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"DiffBIR did not finish within {self.timeout_seconds:g}s and was "
                    f"killed: {exc}"
                ) from exc

            if completed.returncode != 0:
                # Surface stderr: DiffBIR's most common failure here is a missing
                # dependency in its own venv (torchsde, lpips, xformers), and the
                # operator needs the line, not "exit status 1".
                raise RuntimeError(
                    f"DiffBIR exited {completed.returncode}: "
                    f"{(completed.stderr or completed.stdout or '').strip()[-2000:]}"
                )

            restored: List[Image.Image] = []
            absent: List[str] = []
            for stem in stems:
                produced = output_dir / f"{stem}_0.png"
                if not produced.is_file():
                    absent.append(produced.name)
                    continue
                with Image.open(produced) as opened:
                    opened.load()
                    restored.append(opened.convert("RGB"))
            if absent:
                raise RuntimeError(
                    f"DiffBIR exited 0 but wrote no result for {len(absent)} of the "
                    f"{len(stems)} staged face crop(s): {sorted(absent)}. "
                    f"stdout: {(completed.stdout or '').strip()[-1000:]}"
                )
            return restored

    def restore_face(self, crop: Image.Image, **params: Any) -> Image.Image:
        """One crop, through the batch path. Kept because the per-face contract is
        real and worth pinning on its own (`TestDiffBIRStagingIntegration`), and
        because an engine-shaped API that can restore a single thing is easier to
        reason about than one that cannot.

        It is a delegation rather than a second implementation on purpose: a separate
        copy of the staging, argv and read-back code is exactly how the two would drift
        apart and leave one of them doing per-face subprocesses again.
        """
        return self.restore_faces([crop], **params)[0]


def _raise_unknown_engine(model_id: str):
    raise ValueError(
        f"No skin-enhance loader is configured for model '{model_id}'. "
        f"Only {sorted(set(MODE_ENGINES.values()))} are wired: CodeFormer, SUPIR, "
        "StableSR and GPEN are excluded because they are non-commercial or unlicensed "
        "(#111 decision 1)."
    )


def make_gfpgan_loader(model_id: str):
    """Lazy loader factory for the Faithful-mode face restorer.

    Guards the torch and gfpgan imports so they run only at load time; the app boots
    with neither installed. The device is a *constructor argument* because
    `GFPGANer` is a plain class, not an `nn.Module` - there is no `.to()` and no
    `enhance_model()`, which is exactly what the first cut called.
    """

    def _loader():
        if model_id != "gfpgan":
            _raise_unknown_engine(model_id)

        import torch  # type: ignore
        from gfpgan import GFPGANer  # type: ignore

        cuda = torch.cuda.is_available()
        restorer = GFPGANer(
            model_path=(settings.GFPGAN_MODEL_PATH or "").strip() or GFPGAN_MODEL_URL,
            upscale=GFPGAN_UPSCALE,  # no model upscale: native resolution per crop
            arch=GFPGAN_ARCH,
            channel_multiplier=GFPGAN_ARCH_CHANNEL_MULTIPLIER,
            bg_upsampler=None,  # background is explicitly left untouched (#111 d4)
            device=torch.device("cuda" if cuda else "cpu"),
        )
        return GFPGANFaceEngine(restorer)

    return _loader


def make_diffbir_loader(model_id: str):
    """Lazy loader factory for the Creative/Flexible refinement engine.

    There is nothing heavy to import here on purpose. DiffBIR is a repository, not
    a package, so "loading the model" means resolving the operator's checkout and
    remembering how to run its CLI. `torch` is still needed, but only for the face
    detector this adapter uses to answer the route's `no_face_detected` refusal -
    and that import happens in `detect_faces`, not here.
    """

    def _loader():
        if model_id != "diffbir":
            _raise_unknown_engine(model_id)

        return DiffBIRFaceEngine(
            repo_path="",
            python_executable=settings.DIFFBIR_PYTHON,
            timeout_seconds=settings.DIFFBIR_TIMEOUT_SECONDS,
        )

    return _loader


def make_skin_loader(engine_id: str):
    """Dispatch to the loader for a mode's engine."""
    return make_gfpgan_loader(engine_id) if engine_id == "gfpgan" else make_diffbir_loader(
        engine_id
    )

# --------------------------------------------------------------------------- #
# Executor
# --------------------------------------------------------------------------- #


#: Stem characters an output key may carry. Everything else becomes `_`.
UNSAFE_STEM_CHARS = re.compile(r"[^A-Za-z0-9._-]")
#: Stem used when sanitising leaves nothing behind, so the key is never a bare
#: `skin_enhanced/_<token>.png`.
DEFAULT_OUTPUT_STEM = "portrait"


def _sanitize_output_stem(source_path: str) -> str:
    """Reduce a caller-supplied key to a stem that is safe inside a storage key.

    The stem is untrusted input: `Path("..").stem` is `".."`, which would mint
    `skin_enhanced/.._<token>.png`. The transform is deliberately boring -
    disallowed characters (including the spaces an uploaded filename may carry)
    become `_`, leading and trailing `.`/`_` are stripped so the stem cannot
    collapse into a traversal segment, and an all-punctuation stem falls back to
    `DEFAULT_OUTPUT_STEM`. Only new derivative keys are affected; no existing
    catalog row changes.
    """
    stem = UNSAFE_STEM_CHARS.sub("_", Path(source_path).stem).strip("._")
    return stem or DEFAULT_OUTPUT_STEM


def build_skin_filename(source_path: str) -> str:
    """Unique output key: `skin_enhanced/<stem>_<12 hex>.png` (#111 decision 7).

    The unique-token suffix is mandatory, not cosmetic. #96 shipped
    `upscaled/<stem>_<scale>x.png` with a second-resolution token that collapsed
    to a shared prefix, so concurrent jobs on one source overwrote each other's
    output and cross-linked their status lookups. 12 hex chars is uuid4's
    collision-free width at any request rate this endpoint will see.
    """
    return f"{OUTPUT_PREFIX}/{_sanitize_output_stem(source_path)}_{uuid.uuid4().hex[:12]}.png"


def _cap_dimension(image: Image.Image) -> Image.Image:
    """Rescale so the longest side is at most MAX_INPUT_DIMENSION (#111 d4)."""
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_INPUT_DIMENSION:
        return image
    scale = MAX_INPUT_DIMENSION / longest
    if width >= height:
        target = (MAX_INPUT_DIMENSION, int(height * scale))
    else:
        target = (int(width * scale), MAX_INPUT_DIMENSION)
    logger.info(
        f"Skin enhance: capping {width}x{height} input to {target[0]}x{target[1]}"
    )
    return image.resize(target, resample=Image.Resampling.LANCZOS)


def _usable_faces(
    engine: Any, image: Image.Image
) -> Tuple[List[FaceBox], List[FaceBox]]:
    """Split detected boxes into (usable, dropped), clamping each into the canvas.

    Out-of-canvas coordinates are *clamped*, not discarded. S3FD routinely returns a
    box a few pixels outside the frame for tight crops and selfies (`x0 = -4`,
    `y1 = height + 2`), and a subject who fills the frame legitimately has a
    negative x0 - refusing those turns a perfectly good portrait into a
    `no_face_detected` 400. The alignment floor is re-applied to the clamped box, so
    a face whose *visible* part is under MIN_FACE_DIMENSION is still dropped: it
    still has no landmarks worth aligning to.

    Dropped boxes are logged, not silently ignored, but they are not restored.
    """
    width, height = image.size
    usable: List[FaceBox] = []
    dropped: List[FaceBox] = []
    for box in engine.detect_faces(image) or []:
        x0, y0, x1, y1 = (int(v) for v in box)
        cx0, cy0 = max(0, min(x0, width)), max(0, min(y0, height))
        cx1, cy1 = max(0, min(x1, width)), max(0, min(y1, height))
        if (cx1 - cx0) < MIN_FACE_DIMENSION or (cy1 - cy0) < MIN_FACE_DIMENSION:
            dropped.append((x0, y0, x1, y1))
            continue
        usable.append((cx0, cy0, cx1, cy1))
    if dropped:
        logger.info(
            f"Skin enhance: ignoring {len(dropped)} detected box(es) with less than "
            f"{MIN_FACE_DIMENSION}px of visible area after clamping into the canvas"
        )
    return usable, dropped


def _load_source_image(image_path: str, db: Optional[Session]) -> Image.Image:
    """Resolve, video-check and decode the source image (steps 1-3).

    Video is refused by *name* here rather than ignored (#111 decision 6): a user
    who hands over a portrait video is otherwise told nothing at all. The catalog
    content_type is authoritative when the asset is known; the extension is the
    fallback for a key with no row, because the answer must not depend on whether
    a MediaAsset happens to exist.
    """
    content_type: Optional[str] = None
    if db is not None:
        try:
            asset = db.query(MediaAsset).filter(MediaAsset.file_path == image_path).first()
            if asset is not None:
                content_type = asset.content_type
        except Exception as exc:  # a catalog hiccup must not mask the real error
            logger.warning(f"Skin enhance: catalog lookup for '{image_path}' failed: {exc}")
            db.rollback()

    extension = Path(image_path).suffix.lower()
    is_video = (content_type or "").lower().startswith(VIDEO_CONTENT_PREFIXES) or (
        extension in VIDEO_EXTENSIONS
    )
    if is_video:
        raise HTTPException(
            status_code=400,
            detail=(
                "video_input_not_supported: Skin enhancement is images only in v1 "
                "(#111 decision 6). Extract a still frame and enhance that instead. "
                f"Refused '{image_path}' as a video."
            ),
        )

    # Source bytes come from storage and nowhere else. `image_path` is
    # caller-controlled, so probing the server's own filesystem with it would make
    # this endpoint an arbitrary local file reader whose contents then get
    # re-uploaded to storage as a PNG derivative. app/routers/upscale.py already
    # loads strictly from storage; this now matches it.
    raw = download_object(image_path)
    if raw is None:
        raise HTTPException(
            status_code=400,
            detail=f"source_not_found: Source image '{image_path}' was not found in storage.",
        )

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image.convert("RGB")
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"source_unreadable: Source image '{image_path}' is unreadable or corrupt: {exc}",
        )


def run_skin_enhancement(
    image_path: str,
    mode: str = DEFAULT_MODE,
    preset: Optional[str] = None,
    sharpen: int = 0,
    smart_grain: int = 0,
    skin_detail: int = DEFAULT_SKIN_DETAIL,
    db: Optional[Session] = None,
) -> dict:
    """Run face-crop skin enhancement on a portrait and return the derivative.

    Phases:
    1. Resolve the source: refuse video by name, download, decode, cap at 8192.
       This runs *before* the lock: a MinIO round trip and a PNG decode contend for
       nothing the lock protects.
    2. Resolve the engine and its inference parameters (pure table lookup).
    3. Ask the VRAM guard for admission on the single engine this mode names.
       There is deliberately no downgrade ladder here: silently substituting
       GFPGAN for a requested Creative run would change the semantics the user
       asked for, which is the same class of lie as a silent slider clamp.
    4. Lazy-load the engine through model_registry.
    5. Detect faces. No usable face is a 400, not a silent no-op.
    6. Restore the face crops at native resolution and paste them back, so every pixel
       outside the boxes is carried over from the source untouched. How the crops
       reach the engine depends on what the engine is: one `restore_faces` call for
       the whole request when it offers one (DiffBIR, where a call is a process and
       each process reloads the models), the per-face `restore_face` loop when it does
       not (GFPGAN, whose model is resident across calls). Either way the faces are
       restored one at a time inside the engine, and neither shape ever sees a
       background pixel.
    7. Apply the post-filters: sharpen and smart_grain over the whole image in
       every mode, plus Faithful-mode texture retention scoped to the face boxes.
    8. Encode real PNG bytes, upload to skin_enhanced/<stem>_<token>.png and
       persist a MediaAsset whose source_path points at the input, so
       BeforeAfterModal pairs before/after with no new UI. Also outside the lock:
       phases 2-7 hold it, and a Creative run is the slow one - #111 states a ~60s
       per-image design target for it, which is why keeping the upload inside would
       block every other image and audio inference request for two more network
       round trips. That 60s is a target, not a measurement: no DiffBIR run has been
       timed in this repo.
    9. Return COMPLETED, or the labeled degraded envelope at HTTP 200 whenever
       admission or inference could not happen (#111 decision 8).
    """
    # 1. Source resolution (outside the lock - see the docstring).
    image = _load_source_image(image_path, db)
    image = _cap_dimension(image)

    with INFERENCE_LOCK:
        # Invariant: INFERENCE_LOCK serializes admission and inference so eviction
        # cannot occur while another request is mid-inference. Phases 2-7 stay
        # inside it; the storage and catalog work in phase 8 deliberately does not.

        # 2. Engine + inference parameters (pure)
        engine_id, restore_params = resolve_engine_params(mode, preset, skin_detail)

        # 3. Admission check
        try:
            selected_model_id = vram_guard.select_fitting_model(
                candidate_ids=[engine_id],
                working_overhead_gb=WORKING_OVERHEAD_GB,
            )
        except VRAMRefusalError as exc:
            logger.warning(f"Skin enhance refused: {exc.reason} - {exc.message}")
            return exc.to_degraded_response().model_dump()
        except Exception as exc:
            logger.error(f"Unexpected error during VRAM admission check: {exc}")
            return make_degraded_response(
                reason=DegradedReason.NO_GPU.value,
                message=f"Failed to check GPU availability: {str(exc)}",
            ).model_dump()

        # 4. Lazy load via model_registry
        try:
            engine = model_registry.load_model(
                selected_model_id,
                loader_handle=make_skin_loader(selected_model_id),
            )
        except Exception as exc:
            logger.error(f"Failed to load skin engine '{selected_model_id}': {exc}")
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Failed to load local model '{selected_model_id}': {str(exc)}",
                model_id=selected_model_id,
            ).model_dump()

        # 5. Face detection
        try:
            usable, dropped = _usable_faces(engine, image)
        except Exception as exc:
            logger.error(f"Face detection failed for '{selected_model_id}': {exc}")
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Face detection failed for '{selected_model_id}': {str(exc)}",
                model_id=selected_model_id,
            ).model_dump()

        if not usable:
            raise HTTPException(
                status_code=400,
                detail=(
                    "no_face_detected: No face was found in "
                    f"'{image_path}', and skin enhancement only restores detected "
                    "faces (#111 decision 4). "
                    + (
                        f" {len(dropped)} box(es) had less than {MIN_FACE_DIMENSION}px of "
                        "visible area once clamped into the canvas, so there was nothing "
                        "to align."
                        if dropped
                        else ""
                    )
                ),
            )

        # 6. Restore the face crops and paste them back. Every pixel outside these boxes
        # is carried over from the source untouched, in both shapes below.
        #
        # Two engine shapes, one rule. An engine that offers `restore_faces` is asked
        # for the whole request in a single call, because for DiffBIR a call is a
        # *process*: `--input` is a folder and every invocation reloads SwinIR, the
        # conditional diffusion model and SD 2.1, so the per-face loop made an N-face
        # group shot pay the model load N times. An engine without that method
        # (GFPGAN) keeps the per-face loop, which is the right shape for it: its model
        # is resident in this process - `model_registry` caches the loaded instance -
        # so its Nth face is one forward pass, not one reload. Nothing about the
        # response changes between the two.
        restored = image.copy()
        crops = [image.crop(box) for box in usable]
        batch_restore: Optional[Callable[..., Sequence[Image.Image]]] = getattr(
            engine, "restore_faces", None
        )
        enhanced_crops: Sequence[Image.Image]
        if callable(batch_restore):
            try:
                enhanced_crops = (
                    batch_restore(crops, **restore_params)
                    if restore_params
                    else batch_restore(crops)
                )
            except Exception as exc:
                # One process owns every crop, so a failure here is every face's
                # failure, not one face's. Same envelope and the same `Face i/n` log
                # shape as the per-face path, with the count that actually failed.
                logger.error(
                    f"Faces 1-{len(crops)}/{len(crops)} failed on '{selected_model_id}' "
                    f"in one batched restore: {exc}"
                )
                return make_degraded_response(
                    reason=DegradedReason.LOAD_FAILED.value,
                    message=(
                        f"All {len(crops)} face crops failed to restore on "
                        f"'{selected_model_id}' in a single batched run: {str(exc)}"
                    ),
                    model_id=selected_model_id,
                ).model_dump()
            if len(enhanced_crops) != len(crops):
                # Unreachable through `DiffBIRFaceEngine`, which raises instead. Kept
                # because the seam is duck-typed: a short list would paste every face
                # after the gap onto the *previous* face's box, silently.
                logger.error(
                    f"'{selected_model_id}' returned {len(enhanced_crops)} restored "
                    f"crops for {len(crops)} staged ones; refusing to guess the pairing"
                )
                return make_degraded_response(
                    reason=DegradedReason.LOAD_FAILED.value,
                    message=(
                        f"'{selected_model_id}' returned {len(enhanced_crops)} restored "
                        f"faces for {len(crops)} detected faces, so the results cannot be "
                        "paired with their boxes"
                    ),
                    model_id=selected_model_id,
                ).model_dump()
        else:
            per_face: List[Image.Image] = []
            for index, crop in enumerate(crops, start=1):
                try:
                    if restore_params:
                        per_face.append(engine.restore_face(crop, **restore_params))
                    else:
                        per_face.append(engine.restore_face(crop))
                except Exception as exc:
                    logger.error(
                        f"Face {index}/{len(crops)} failed on '{selected_model_id}': {exc}"
                    )
                    return make_degraded_response(
                        reason=DegradedReason.LOAD_FAILED.value,
                        message=(
                            f"Face {index} of {len(crops)} failed to restore on "
                            f"'{selected_model_id}': {str(exc)}"
                        ),
                        model_id=selected_model_id,
                    ).model_dump()
            enhanced_crops = per_face

        for index, (box, crop, enhanced_crop) in enumerate(
            zip(usable, crops, enhanced_crops), start=1
        ):
            x0, y0, x1, y1 = box
            if enhanced_crop.size != crop.size:
                logger.warning(
                    f"Face {index} restored at {enhanced_crop.size} instead of "
                    f"{crop.size}; resizing to preserve the crop footprint"
                )
                enhanced_crop = enhanced_crop.resize(crop.size, resample=Image.Resampling.LANCZOS)
            restored.paste(enhanced_crop.convert("RGB"), (x0, y0))

        # 7. Post-filters.
        # sharpen and smart_grain are whole-image controls in every mode, exactly
        # as Magnific documents them. Faithful-mode texture retention is scoped to
        # the restored face boxes instead: skin_detail is a *skin* control, and
        # #111 decision 4 requires the background to be left untouched. It is
        # applied before the global filters so it does not amplify the grain the
        # smart_grain pass is about to add.
        if mode == "faithful":
            strength = map_skin_detail_to_texture_retention(skin_detail)
            if strength > 0.0:
                for (x0, y0, x1, y1) in usable:
                    box = (x0, y0, x1, y1)
                    # Source crop first: the texture being re-injected is the
                    # *original's*, not the restored crop's own high frequencies.
                    retained = apply_texture_retention(
                        image.crop(box), restored.crop(box), strength
                    )
                    restored.paste(retained, (x0, y0))

        finished = apply_skin_post_filters(restored, sharpen=sharpen, smart_grain=smart_grain)

    # 8. Encode real PNG bytes, upload, persist the derivative with lineage. Outside
    # the lock on purpose: the lock exists to keep eviction out of inference, and
    # holding it across a PNG encode, a MinIO upload and a catalog commit would idle
    # every other inference request for three round trips it does not need to guard.
    out_buf = io.BytesIO()
    finished.save(out_buf, format="PNG", optimize=True)
    png_bytes = out_buf.getvalue()

    filename = build_skin_filename(image_path)
    if not upload_object(png_bytes, filename, content_type="image/png"):
        logger.error(f"Failed to upload skin-enhanced image '{filename}' to storage")
        return make_degraded_response(
            reason=DegradedReason.LOAD_FAILED.value,
            message="Failed to upload skin-enhanced image to storage",
            model_id=selected_model_id,
        ).model_dump()

    if db is not None:
        try:
            title = f"Skin Enhanced: {Path(image_path).stem} ({mode})"
            asset = MediaAsset(
                title=title,
                file_path=filename,
                file_size=len(png_bytes),
                content_type="image/png",
                duration=0.0,
                # Lineage: BeforeAfterModal pairs on this, no new UI needed.
                source_path=image_path,
                embedding=get_embedding(title),
            )
            db.add(asset)
            db.commit()
        except Exception as exc:
            logger.error(f"Failed to save skin-enhanced asset: {exc}")
            db.rollback()
            # The object is already in storage, so COMPLETED here would hand the
            # caller a filename and a URL for an object with no catalog row, and
            # the source_path lineage #111 decision 7 requires would be silently
            # absent. Same rule the upload failure above follows.
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Failed to save skin-enhanced asset to the catalog: {str(exc)}",
                model_id=selected_model_id,
            ).model_dump()

    # 9. Response
    response_parameters: Dict[str, Any] = {
        "sharpen": sharpen,
        "smart_grain": smart_grain,
        "skin_detail": skin_detail,
    }
    if restore_params:
        response_parameters.update(
            {
                "prompt": restore_params["prompt"],
                "guidance_scale": restore_params["guidance_scale"],
                "condition_noise": restore_params["condition_noise"],
                "num_inference_steps": restore_params["num_inference_steps"],
            }
        )
    else:
        response_parameters["texture_retention"] = (
            map_skin_detail_to_texture_retention(skin_detail)
        )

    return {
        "status": "COMPLETED",
        "mode": mode,
        "preset": (preset or DEFAULT_FLEXIBLE_PRESET) if mode == "flexible" else None,
        "engine": selected_model_id,
        "source_path": image_path,
        "filename": filename,
        "url": generate_url(filename),
        "faces_enhanced": len(usable),
        "face_boxes": [list(box) for box in usable],
        "faces_skipped": len(dropped),
        "image_size": list(finished.size),
        "parameters": response_parameters,
    }


def describe_skin_surface() -> Dict[str, Any]:
    """Machine-readable description of the endpoint's input surface.

    Exposed by `GET /api/skin-enhance/presets` so the panel (ticket #137) can
    render the mode switch, the preset list and the slider ranges without
    hardcoding a second copy of the contract that could drift from this one.
    """
    return {
        "modes": list(SKIN_MODES),
        "default_mode": DEFAULT_MODE,
        "engines": dict(MODE_ENGINES),
        "presets": {
            name: {
                "prompt": preset["prompt"],
                "guidance_scale": preset["guidance_scale"],
                "condition_noise": preset["condition_noise"],
                "description": preset["description"],
            }
            for name, preset in FLEXIBLE_PRESETS.items()
        },
        "default_preset": DEFAULT_FLEXIBLE_PRESET,
        "sliders": {
            "sharpen": {"min": SLIDER_MIN, "max": SLIDER_MAX, "default": 0},
            "smart_grain": {"min": SLIDER_MIN, "max": SLIDER_MAX, "default": 0},
            "skin_detail": {
                "min": SLIDER_MIN,
                "max": SLIDER_MAX,
                "default": DEFAULT_SKIN_DETAIL,
            },
        },
        # Decision 2's accepted consequence: skin_detail is not the same physical
        # knob per mode, so the panel has to be told what the slider means now.
        "skin_detail_semantics": {
            "faithful": "texture retention strength (post-filter)",
            "creative": "DiffBIR guidance scale",
            "flexible": "DiffBIR guidance scale (anchored on the preset value at 80)",
        },
        "max_input_dimension": MAX_INPUT_DIMENSION,
        "min_face_dimension": MIN_FACE_DIMENSION,
        "video_supported": False,
        "faces_only": True,
    }
