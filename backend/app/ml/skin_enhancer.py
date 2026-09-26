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
  16 GB floor from #98.
- Decision 4: face-crop only. Detect, restore each face at native resolution, paste
  back, leave the background untouched. The 512 tile engine is not reused. Max
  input dimension is capped at 8192, the same ceiling the upscaler uses.
- Decision 6: video input is refused with a named 400 reason, not ignored.
- Decision 8: on VRAM refusal or a missing GPU, the labeled degraded envelope
  (DegradedResponse) is returned at HTTP 200. Nothing here ever fabricates payload
  bytes to stand in for a result.

Strictly guards and lazy-loads torch, gfpgan, facexlib and diffusers so the app
boots and non-GPU environments function cleanly.
"""

from __future__ import annotations

import io
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from fastapi import HTTPException
from PIL import Image, ImageFilter
from sqlalchemy.orm import Session

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

#: Creative mode has no preset to inherit a guidance scale from, so it carries
#: one of its own: DiffBIR's own webui defaults `--scale` to 3.5.
CREATIVE_PROMPT = (
    "high quality portrait photograph of a real person, detailed natural skin, "
    "sharp eyes, photorealistic"
)
CREATIVE_BASE_GUIDANCE = 3.5
#: Creative mode also has no preset for condition noise, so it takes a fixed
#: mid-range value: enough headroom for a single unguided prompt, well below the
#: most creative Flexible preset.
CREATIVE_CONDITION_NOISE = 0.25

#: DiffBIR v2.1 ships 10-step samplers (per its release notes) and #111 budgets
#: Creative/Flexible at <= 60s per image, so the 10-step path is the one that
#: fits the budget. Chosen, not measured.
DIFFBIR_INFERENCE_STEPS = 10

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


class GFPGANFaceEngine:
    """Adapter over GFPGANer: facexlib for detection, GFPGAN for restoration.

    `restore_face` is handed one crop and returns the restored crop at the same
    size, so the executor stays in control of the crop / paste-back loop and the
    background provably cannot be touched.
    """

    def __init__(self, restorer: Any, face_helper: Any):
        self.restorer = restorer
        self.face_helper = face_helper

    def detect_faces(self, image: Image.Image) -> List[FaceBox]:
        _landmarks, boxes = self.face_helper.align_wrtk(image)
        return [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in (boxes or [])]

    def restore_face(self, crop: Image.Image, **params: Any) -> Image.Image:
        if params:
            raise ValueError(
                "Faithful mode's engine (GFPGAN) has no prompt or guidance control; "
                f"unexpected parameters forwarded: {sorted(params)}"
            )
        restored = self.restorer.enhance(
            crop, has_aligned=False, only_center_face=False, paste_back=True
        )
        if not isinstance(restored, Image.Image):
            raise ValueError(
                f"Unrecognized GFPGAN output type: {type(restored).__name__}"
            )
        return restored.convert("RGB")


class DiffBIRFaceEngine:
    """Adapter over diffusers' DiffBIRPipeline for one face crop at a time."""

    def __init__(self, pipeline: Any, face_helper: Any):
        self.pipeline = pipeline
        self.face_helper = face_helper

    def detect_faces(self, image: Image.Image) -> List[FaceBox]:
        _landmarks, boxes = self.face_helper.align_wrtk(image)
        return [(int(b[0]), int(b[1]), int(b[2]), int(b[3])) for b in (boxes or [])]

    def restore_face(self, crop: Image.Image, **params: Any) -> Image.Image:
        result = self.pipeline(
            image=crop,
            prompt=params["prompt"],
            # DiffBIR's condition noise is 0..1 in the upstream repo's webui and
            # 0..100 in the diffusers port; convert rather than silently
            # under-drive the knob.
            noise_level=int(round(float(params["condition_noise"]) * 100)),
            guidance_scale=float(params["guidance_scale"]),
            num_inference_steps=int(params["num_inference_steps"]),
        )
        output = getattr(result, "images", None)
        if output is None:
            output = result
        if isinstance(output, (list, tuple)):
            if not output:
                raise ValueError("DiffBIR returned an empty image list")
            output = output[0]
        if hasattr(output, "cpu"):
            output = output.cpu().numpy()
        if isinstance(output, np.ndarray) and output.ndim == 3 and output.shape[0] in (1, 3):
            output = np.transpose(output, (1, 2, 0))
        return Image.fromarray(np.asarray(output).astype(np.uint8)).convert("RGB")


def _raise_unknown_engine(model_id: str):
    raise ValueError(
        f"No skin-enhance loader is configured for model '{model_id}'. "
        f"Only {sorted(set(MODE_ENGINES.values()))} are wired: CodeFormer, SUPIR, "
        "StableSR and GPEN are excluded because they are non-commercial or unlicensed "
        "(#111 decision 1)."
    )


def make_gfpgan_loader(model_id: str):
    """Lazy loader factory for the Faithful-mode face restorer.

    Guards gfpgan, facexlib and torch imports so they run only at load time.
    On CUDA the weights are moved with `enhance_model()` (GFPGAN's own
    half-precision / CPU-offload path) rather than `to('cuda')`, mirroring the
    offload strategy app/ml/image.py uses for FLUX.
    """

    def _loader():
        if model_id != "gfpgan":
            _raise_unknown_engine(model_id)

        import torch  # type: ignore
        from facexlib.face_helper import FaceHelper  # type: ignore
        from gfpgan import (  # type: ignore
            GFPGAN_VERSION_1_3,
            GFPGAN_VERSION_1_4,
            GFPGANer,
        )

        # v1.4 is the sharper, more identity-preserving checkpoint; v1.3 is the
        # fallback for older gfpgan installs that predate it. A CPU-only host
        # never reaches this code (the VRAM guard refuses first), so the version
        # choice there only has to be constructible.
        version = GFPGAN_VERSION_1_4 if torch.cuda.is_available() else GFPGAN_VERSION_1_3
        # One detector, shared with the restorer, so we are not holding two
        # resident copies of the S3FD model.
        face_helper = FaceHelper(
            max_num=20,  # a group shot must not silently drop faces 6..20
            min_size=MIN_FACE_DIMENSION,
            detection_model="s3fd",
            save_ext="png",
        )
        restorer = GFPGANer(
            model_path=version,
            upscale=1,  # no model upscale: each face is restored at native resolution
            arch="clean",
            channel_multiplier=2,
            bg_upsampler=None,  # background is explicitly left untouched (#111 d4)
            face_helper=face_helper,
        )
        if torch.cuda.is_available():
            restorer.enhance_model()
        else:
            restorer.to("cpu")
        return GFPGANFaceEngine(restorer, face_helper)

    return _loader


def make_diffbir_loader(model_id: str):
    """Lazy loader factory for the Creative/Flexible refinement pipeline.

    Guards diffusers and torch imports so they run only at load time.
    `enable_tiling()` is mandatory, not an optimization: the registry advertises
    DiffBIR at 8 GB, which is the figure the v2.1 release notes publish *for tiled
    inference only*. Without tiling the true footprint is higher and the guard
    would be admitting a job that OOMs.
    """

    def _loader():
        if model_id != "diffbir":
            _raise_unknown_engine(model_id)

        import torch  # type: ignore
        from diffusers import DiffBIRPipeline  # type: ignore
        from facexlib.face_helper import FaceHelper  # type: ignore

        cuda = torch.cuda.is_available()
        pipe = DiffBIRPipeline.from_pretrained(
            "XPixelGroup/DiffBIR",
            torch_dtype=torch.float16 if cuda else torch.float32,
        )
        pipe.enable_tiling()
        if cuda:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cpu")
        # The pipeline itself does no face detection, so the adapter's FaceHelper
        # has to be built here - handing it None instead produced an engine whose
        # detect_faces raised AttributeError, which the executor turned into a
        # LOAD_FAILED envelope: every Creative and Flexible request degraded.
        # Same configuration as the GFPGAN loader, so a Faithful run and a
        # Creative run agree on what a face is and what is too small to align.
        # This is a second resident S3FD when both engines are loaded; DiffBIR's
        # published 8 GB is the diffusion stack, and the detector is the same
        # marginal cost its own loader already accepts.
        face_helper = FaceHelper(
            max_num=20,  # a group shot must not silently drop faces 6..20
            min_size=MIN_FACE_DIMENSION,
            detection_model="s3fd",
            save_ext="png",
        )
        return DiffBIRFaceEngine(pipe, face_helper)

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
    6. Restore each face crop at native resolution and paste it back, sequentially,
       so a group shot's peak VRAM stays at one crop rather than N.
    7. Apply the post-filters: sharpen and smart_grain over the whole image in
       every mode, plus Faithful-mode texture retention scoped to the face boxes.
    8. Encode real PNG bytes, upload to skin_enhanced/<stem>_<token>.png and
       persist a MediaAsset whose source_path points at the input, so
       BeforeAfterModal pairs before/after with no new UI. Also outside the lock:
       phases 2-7 hold it, and a Creative run is budgeted at up to 60s, so keeping
       the upload inside would block every other image and audio inference request
       for two more network round trips.
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

        # 6. Restore each face crop, sequentially, and paste it back. Every pixel
        # outside these boxes is carried over from the source untouched.
        restored = image.copy()
        for index, (x0, y0, x1, y1) in enumerate(usable, start=1):
            crop = image.crop((x0, y0, x1, y1))
            try:
                if restore_params:
                    enhanced_crop = engine.restore_face(crop, **restore_params)
                else:
                    enhanced_crop = engine.restore_face(crop)
            except Exception as exc:
                logger.error(
                    f"Face {index}/{len(usable)} failed on '{selected_model_id}': {exc}"
                )
                return make_degraded_response(
                    reason=DegradedReason.LOAD_FAILED.value,
                    message=(
                        f"Face {index} of {len(usable)} failed to restore on "
                        f"'{selected_model_id}': {str(exc)}"
                    ),
                    model_id=selected_model_id,
                ).model_dump()
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
