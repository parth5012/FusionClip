"""Contract tests for the two *real* third-party skin engines (#138 review fix).

Why this module exists
----------------------
The 64 tests that shipped with #112 all passed while every mode of this endpoint
was non-functional on real hardware. The reason is a specific, repeatable trap:
each test injected a fake ``gfpgan`` / ``facexlib`` / ``diffusers`` module that
defined exactly the symbols the *production code* referenced. The fakes were
written from the production code, so they asserted the API the code invented
rather than the API that ships. ``FaceHelper.align_wrtk`` does not exist,
``GFPGANer`` has no ``face_helper=`` kwarg, no ``enhance_model()`` and no
``.to()``, ``gfpgan`` exports no ``GFPGAN_VERSION_1_3``/``_1_4``, and
``diffusers`` has no ``DiffBIRPipeline`` at all - every one of those references
would have raised on a machine with the real packages installed.

So the assertions here come in three layers, weakest assumption first:

1. ``TestNoInventedApiSymbols`` reads the *source* of ``skin_enhancer.py`` and
   fails if it names any symbol that does not exist upstream. It needs no GPU
   and no torch, so it runs everywhere, including this suite.
2. ``TestRealGfpganApiContract`` / ``TestRealFacexlibApiContract`` introspect the
   **installed** ``gfpgan`` and ``facexlib`` and assert that every symbol and
   signature the production code depends on is really there. These use
   ``pytest.importorskip`` and are therefore SKIPPED wherever torch is absent -
   see ``TestSkipIsLoud`` below, which is deliberate: a green run that skipped
   the contract tests has verified nothing about the real API.
3. ``TestStubSignaturesMirrorRealApi`` pins the fakes used by the no-GPU CI path
   to the real signatures, so the stubs cannot drift back into defining whatever
   the code happens to call. Where the real package is importable the mirror is
   compared against it; where it is not, the mirror's own signature is at least
   checked against the documented upstream signature literal.

The DiffBIR half is a subprocess integration, so its contract is the argv we
build: ``TestDiffBIRArgvContract`` asserts on the argv itself and parses it
through a mirror of ``inference.py::parse_args`` (checked out at DiffBIR commit
5c2d6c1), because a flag that is spelled wrong fails only at runtime on a GPU.
"""

import ast
import inspect
import io
import re
import sys
import types
from argparse import ArgumentParser
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[2]
SKIN_MODULE_PATH = REPO_ROOT / "backend" / "app" / "ml" / "skin_enhancer.py"


# --------------------------------------------------------------------------- #
# Layer 1: no symbol the production code names may be absent upstream
# --------------------------------------------------------------------------- #

#: Regexes matching attribute / kwarg names that do not exist in gfpgan 1.3.8,
#: facexlib 0.3.0 or in DiffBIR, together with why each one was believed to exist.
#: Every entry here shipped in #112 and would raise on a machine with the real
#: packages. They are regexes rather than plain substrings because a substring
#: scan cannot tell `GFPGANer(face_helper=h)` from our own `self._face_helper = ...`.
INVENTED_SYMBOLS = {
    r"\balign_wrtk\b": (
        "facexlib 0.3.0 has no `align_wrtk` on any class. Face detection goes "
        "through `FaceRestoreHelper.read_image` + `get_face_landmarks_5`, and the "
        "landmarks list is then read off `helper.det_faces`."
    ),
    r"(?<![\w.])face_helper\s*=": (
        "passed to `GFPGANer(...)`: the constructor takes (model_path, upscale, arch, "
        "channel_multiplier, bg_upsampler, device) and builds its own "
        "`FaceRestoreHelper` internally. There is no `face_helper=` kwarg; the built "
        "instance is reachable as `restorer.face_helper` after construction."
    ),
    r"\benhance_model\b": (
        "`GFPGANer` has no `enhance_model()`. It is not an nn.Module and has no "
        "`.to()` either - the device is a constructor argument."
    ),
    r"\bGFPGAN_VERSION_1_": (
        "gfpgan 1.3.8 exports no `GFPGAN_VERSION_1_3` / `GFPGAN_VERSION_1_4` "
        "constants. `model_path` is a filesystem path or an https:// URL that "
        "`GFPGANer` downloads via basicsr's load_file_from_url."
    ),
    r"\bDiffBIRPipeline\b": (
        "XPixelGroup/DiffBIR is not a diffusers pipeline and is not on PyPI. "
        "`from diffusers import DiffBIRPipeline` cannot work; the engine shells "
        "out to `<repo>/inference.py` instead."
    ),
    r"(?<![\w.])FaceHelper\s*\(": (
        "`facexlib.face_helper.FaceHelper` (the S3FD-era helper with a "
        "`detection_model=` argument) is not the class GFPGAN uses. "
        "`FaceRestoreHelper` in `facexlib.utils.face_restoration_helper` is, and "
        "its detector is chosen with `det_model=`, whose only valid values are "
        "`retinaface_resnet50` and `retinaface_mobile0.25` - `s3fd` raises "
        "NotImplementedError."
    ),
    r"detection_model\s*=\s*[\"']s3fd[\"']": (
        "facexlib 0.3.0's `init_detection_model` implements only "
        "`retinaface_resnet50` and `retinaface_mobile0.25`; any other name - "
        "including `s3fd` - raises NotImplementedError."
    ),
    r"\benable_tiling\b": (
        "There is no diffusers pipeline to tile. DiffBIR's tiling is the "
        "`--cleaner_tiled` / `--cldm_tiled` command-line pair."
    ),
}


def _code_only(source: str) -> str:
    """Normalise a module down to its executable tokens, for substring matching.

    The denylist below names the API the *old* code invented, and this module's
    comments have to discuss those names in order to explain why they are banned.
    Scanning raw text would therefore fail on its own documentation; scanning
    tokens cannot. Tokens are joined with a single space so that word-boundary
    anchors still work (`import` + `GFPGAN_VERSION_1_4` must not become
    `importGFPGAN_VERSION_1_4`), and quotes are unified so a denylist entry can be
    written the way a human writes it (`face_helper = h`, not `face_helper=` glued
    to the `=`).
    """
    import io
    import tokenize

    docstring_lines = set()
    for node in ast.walk(ast.parse(source)):
        if not isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        ):
            continue
        body = getattr(node, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            docstring_lines.update(
                range(body[0].lineno, (body[0].end_lineno or body[0].lineno) + 1)
            )

    pieces: list = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (
            tokenize.COMMENT,
            tokenize.NL,
            tokenize.NEWLINE,
            tokenize.INDENT,
            tokenize.DEDENT,
            tokenize.ENDMARKER,
        ):
            continue
        if token.type == tokenize.STRING and token.start[0] in docstring_lines:
            continue
        pieces.append(token.string)
    return " ".join(pieces).replace("'", '"')


class TestNoInventedApiSymbols:
    """Source-level guard. Runs with no torch, no GPU and no gfpgan installed."""

    def test_production_module_names_no_symbol_absent_upstream(self):
        code = _code_only(SKIN_MODULE_PATH.read_text(encoding="utf-8"))
        offenders = [
            f"{pattern!r} - {why}"
            for pattern, why in INVENTED_SYMBOLS.items()
            if re.search(pattern, code)
        ]
        assert not offenders, (
            "skin_enhancer.py references API that does not exist upstream; every "
            "mode would raise on a real install:\n  " + "\n  ".join(offenders)
        )

    def test_the_denylist_would_catch_the_old_implementation(self):
        """Guards the guard. `INVENTED_SYMBOLS` is only useful if the scan actually
        matches code, so it is pointed at the pre-fix form of the loader and must
        report hits. If someone 'simplifies' the denylist into a list of empty
        strings, this fails instead of the denylist silently passing forever."""
        old_loader = (
            "from gfpgan import GFPGAN_VERSION_1_4, GFPGANer\n"
            "from facexlib.face_helper import FaceHelper\n"
            "helper = FaceHelper(detection_model='s3fd')\n"
            "restorer = GFPGANer(model_path=v, face_helper=helper)\n"
            "restorer.enhance_model()\n"
            "restorer.to('cpu')\n"
            "helper.align_wrtk(image)\n"
            "from diffusers import DiffBIRPipeline\n"
        )
        code = _code_only(old_loader)
        hits = [pattern for pattern in INVENTED_SYMBOLS if re.search(pattern, code)]
        assert len(hits) >= 7, (
            f"the denylist only matched {hits}; it is supposed to catch the exact "
            "call sequence that shipped in #112"
        )

    def test_gfpgan_import_is_confined_to_the_loader_closure(self):
        """`torch` and `gfpgan` may only be imported inside a loader, never at
        module scope, or the app stops booting on a torch-free host."""
        source = SKIN_MODULE_PATH.read_text(encoding="utf-8")
        module_level_imports = re.findall(
            r"^(?:from|import)\s+(torch|gfpgan|facexlib|diffusers)\b", source, re.MULTILINE
        )
        assert not module_level_imports, (
            "module-scope heavy import(s): " f"{sorted(set(module_level_imports))}"
        )

    def test_heavy_imports_stay_inside_a_nested_def(self):
        """A guard stronger than the previous test: every `import torch` /
        `import gfpgan` / `from gfpgan import ...` line must be indented, i.e.
        lexically inside a function body rather than at module scope."""
        source = SKIN_MODULE_PATH.read_text(encoding="utf-8")
        for number, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if not re.match(r"(?:import|from)\s+(torch|gfpgan|facexlib)\b", stripped):
                continue
            assert line[:1] in (" ", "\t"), (
                f"line {number} imports a heavy dependency at module scope: {stripped!r}"
            )


class TestSkipIsLoud:
    """The contract tests are worthless if they skip silently and nobody reads it.

    Where gfpgan/facexlib are importable, the introspection tests below really
    run; where they are not, they skip. This test does not change that, it just
    records which of the two happened so a reader of a green run is not misled
    into thinking the real API was checked.
    """

    def test_records_whether_real_apis_were_introspected(self, record_property):
        try:
            import gfpgan  # noqa: F401
            import facexlib  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on the host
            record_property("skin_engine_real_apis", f"SKIPPED ({exc})")
            pytest.skip(
                "gfpgan/facexlib are not importable here, so the real-API contract "
                "tests in this module are SKIPPED, not passed. Run this module on a "
                "host with `pip install gfpgan facexlib` to actually check the API."
            )
        record_property("skin_engine_real_apis", "introspected")


# --------------------------------------------------------------------------- #
# Layer 2: introspect the real classes
# --------------------------------------------------------------------------- #


def _param_names(func) -> list:
    return [
        name
        for name, param in inspect.signature(func).parameters.items()
        if param.kind is not inspect.Parameter.VAR_KEYWORD
    ]


class TestRealGfpganApiContract:
    """Asserts the real ``GFPGANer`` really has the API the loader calls.

    SKIPPED without gfpgan installed. To run it: ``pip install gfpgan facexlib``
    (plus their torch/torchvision/opencv deps) and re-run this module.
    """

    def setup_method(self):
        pytest.importorskip(
            "gfpgan",
            reason=(
                "gfpgan is not installed, so the real GFPGANer API cannot be "
                "introspected. This test is SKIPPED, not passed."
            ),
        )

    def test_constructor_accepts_exactly_the_kwargs_the_loader_passes(self):
        """The loader passes model_path/upscale/arch/channel_multiplier/
        bg_upsampler/device. If upstream renames or drops one, every Faithful
        request dies with a TypeError that no stub-based test would see."""
        from gfpgan import GFPGANer

        params = _param_names(GFPGANer.__init__)
        for expected in (
            "model_path",
            "upscale",
            "arch",
            "channel_multiplier",
            "bg_upsampler",
            "device",
        ):
            assert expected in params, (
                f"GFPGANer.__init__ no longer accepts '{expected}'. Real signature: {params}"
            )
        assert "face_helper" not in params, (
            "GFPGANer grew a face_helper kwarg - if you want to use it, re-read its "
            "source first; the current loader relies on restorer.face_helper instead."
        )

    def test_enhance_takes_the_arguments_the_adapter_passes(self):
        from gfpgan import GFPGANer

        params = _param_names(GFPGANer.enhance)
        for expected in ("img", "has_aligned", "only_center_face", "paste_back", "weight"):
            assert expected in params, f"GFPGANer.enhance lost '{expected}': {params}"

    def test_no_offload_api_is_referenced_because_none_exists(self):
        """`enhance_model()` and `.to()` are how the old code moved weights. Neither
        exists on GFPGANer, and their absence is exactly why the old test suite
        (which faked both) stayed green."""
        from gfpgan import GFPGANer

        for invented in ("enhance_model", "to"):
            assert not hasattr(GFPGANer, invented), (
                f"GFPGANer now has .{invented}(); re-read its source before assuming "
                "the constructor-`device=` form is still the only option."
            )

    def test_gfpgan_exports_no_version_constants(self):
        """The old loader did `from gfpgan import GFPGAN_VERSION_1_4`. That name does
        not exist; the import raises ImportError before any of our code runs."""
        import gfpgan

        for invented in ("GFPGAN_VERSION_1_3", "GFPGAN_VERSION_1_4"):
            assert not hasattr(gfpgan, invented), (
                f"gfpgan now exports {invented}; re-read its source before deciding "
                "the model path should stay a literal release URL."
            )

    def test_model_path_constant_is_an_https_url_green_paths_download(self):
        """`GFPGANer.__init__` branches on `model_path.startswith('https://')` and
        calls basicsr's load_file_from_url, so a release URL is a supported input -
        that is what makes the default model path possible without a bundled
        checkpoint."""
        source = inspect.getsource(sys.modules["gfpgan"].utils.GFPGANer.__init__)
        assert "startswith('https://')" in source or 'startswith("https://")' in source, (
            "GFPGANer no longer special-cases https:// model paths; the loader's "
            "default model path must become a local file instead."
        )

    def test_arch_clean_matches_the_checkpoint_the_loader_names(self):
        """`arch` must match the checkpoint or `load_state_dict(strict=True)` raises.
        The loader pins `arch='clean'` and names the v1.2 clean release asset."""
        import app.ml.skin_enhancer as skin_mod

        assert skin_mod.GFPGAN_ARCH == "clean"
        assert skin_mod.GFPGAN_ARCH_CHANNEL_MULTIPLIER == 2
        assert skin_mod.GFPGAN_MODEL_URL.endswith(".pth")
        assert "GFPGANClean" in skin_mod.GFPGAN_MODEL_URL, (
            "arch='clean' loads GFPGANv1Clean; the model URL must name a Clean "
            "checkpoint or load_state_dict(strict=True) fails."
        )

    def test_upscale_is_one_so_the_background_is_not_resampled(self):
        """`upscale=1` plus `bg_upsampler=None` is what implements #111 decision 4's
        "background untouched": GFPGANer pastes the restored faces back into a
        cv2.resize of the input at factor 1, i.e. a no-op copy."""
        import app.ml.skin_enhancer as skin_mod

        assert skin_mod.GFPGAN_UPSCALE == 1


class TestRealFacexlibApiContract:
    """Asserts the real ``FaceRestoreHelper`` really has the API we drive.

    SKIPPED without facexlib installed.
    """

    def setup_method(self):
        pytest.importorskip(
            "facexlib",
            reason=(
                "facexlib is not installed, so the real FaceRestoreHelper API cannot "
                "be introspected. This test is SKIPPED, not passed."
            ),
        )

    def _helper_class(self):
        from facexlib.utils.face_restoration_helper import FaceRestoreHelper

        return FaceRestoreHelper

    def test_helper_has_the_methods_the_adapter_calls(self):
        helper = self._helper_class()
        for method in (
            "read_image",
            "get_face_landmarks_5",
            "align_warp_face",
            "get_inverse_affine",
            "add_restored_face",
            "paste_faces_to_input_image",
            "clean_all",
        ):
            assert hasattr(helper, method), f"FaceRestoreHelper has no .{method}()"

    def test_helper_has_no_align_wrtk(self):
        """`align_wrtk` is the method the old code called in *both* adapters and
        which exists nowhere. This is the single assertion that would have caught
        the original defect had the real package been importable."""
        helper = self._helper_class()
        assert not hasattr(helper, "align_wrtk"), (
            "FaceRestoreHelper has grown an align_wrtk(); re-read its source before "
            "trusting this comment."
        )

    def test_get_face_landmarks_5_takes_the_arguments_we_pass(self):
        helper = self._helper_class()
        params = _param_names(helper.get_face_landmarks_5)
        for expected in ("only_center_face", "eye_dist_threshold", "resize"):
            assert expected in params, f"get_face_landmarks_5 lost '{expected}': {params}"

    def test_det_faces_is_the_public_attribute_holding_detected_boxes(self):
        """`det_faces` is where the boxes live after `get_face_landmarks_5`. It is
        reset by `clean_all()`, which is why detection must not run before a stale
        list is cleared."""
        helper = self._helper_class()
        source = inspect.getsource(helper.get_face_landmarks_5)
        assert "self.det_faces.append" in source
        clean_source = inspect.getsource(helper.clean_all)
        assert "self.det_faces = []" in clean_source

    def test_only_retinaface_variants_are_implemented(self):
        """facexlib 0.3.0's `init_detection_model` supports exactly two names.
        The old code passed `detection_model='s3fd'` to a `FaceHelper` class that
        does not exist anyway; the value `s3fd` is unsupported in either API.

        The function is *not* called - that would download the weights. Its source
        is read instead, which is enough to pin the supported set.
        """
        from facexlib import detection

        source = inspect.getsource(detection.init_detection_model)
        supported = set(re.findall(r"model_name == '([^']+)'", source))
        assert supported == {"retinaface_resnet50", "retinaface_mobile0.25"}, (
            f"facexlib's supported detectors changed to {supported}; the loader's "
            "det_model constant has to be revisited."
        )
        assert "NotImplementedError" in source

    def test_loader_only_names_a_detector_facexlib_implements(self):
        import app.ml.skin_enhancer as skin_mod

        assert skin_mod.DETECT_MODEL in {"retinaface_resnet50", "retinaface_mobile0.25"}, (
            f"DETECT_MODEL={skin_mod.DETECT_MODEL!r} is not implemented by "
            "facexlib 0.3.0 and would raise NotImplementedError at load time."
        )


# --------------------------------------------------------------------------- #
# Layer 3: the CI stubs must mirror the real signatures
# --------------------------------------------------------------------------- #

#: The signature of ``GFPGANer.__init__`` in gfpgan 1.3.8, copied verbatim from
#: ``gfpgan/utils.py``. The mirror below must match it, so that a stub can never
#: again be the only definition of "what GFPGANer accepts".
GFPGANER_INIT_SIGNATURE = (
    "self, model_path, upscale=2, arch='clean', channel_multiplier=2, "
    "bg_upsampler=None, device=None"
)
#: ``GFPGANer.enhance`` in gfpgan 1.3.8, likewise copied verbatim.
GFPGANER_ENHANCE_SIGNATURE = (
    "self, img, has_aligned=False, only_center_face=False, paste_back=True, weight=0.5"
)


class ContractMirrorGFPGANer:
    """A fake ``GFPGANer`` that mirrors the real signature. NOT a definition.

    This is a *contract mirror*: it exists only so the no-GPU CI path can call the
    adapter end-to-end. Its only authority is the real upstream signature, which
    ``TestStubSignaturesMirrorRealApi`` compares against - and against the real
    class itself wherever gfpgan happens to be importable. If the two ever
    disagree, the real one wins and this file is the thing that is wrong.
    """

    def __init__(
        self, model_path, upscale=2, arch="clean", channel_multiplier=2, bg_upsampler=None, device=None
    ):
        self.model_path = model_path
        self.upscale = upscale
        self.arch = arch
        self.channel_multiplier = channel_multiplier
        self.bg_upsampler = bg_upsampler
        self.device = device
        self.enhance_calls = []
        self.face_helper = ContractMirrorFaceRestoreHelper(
            upscale,
            face_size=512,
            crop_ratio=(1, 1),
            det_model="retinaface_resnet50",
            save_ext="png",
            use_parse=True,
            device=device,
            model_rootpath="gfpgan/weights",
        )

    def enhance(self, img, has_aligned=False, only_center_face=False, paste_back=True, weight=0.5):
        """Mirrors the real control flow: clean, read, detect, align, restore, paste."""
        self.enhance_calls.append(
            {
                "img": img,
                "has_aligned": has_aligned,
                "only_center_face": only_center_face,
                "paste_back": paste_back,
                "weight": weight,
            }
        )
        helper = self.face_helper
        helper.clean_all()
        helper.read_image(img)
        helper.get_face_landmarks_5(only_center_face=only_center_face, eye_dist_threshold=5)
        helper.align_warp_face()
        # A real forward pass would run here. The mirror returns the aligned crop
        # brightened, so a paste-back is observable in a test, in BGR like upstream.
        for cropped in helper.cropped_faces:
            helper.add_restored_face(np.clip(cropped.astype(np.int32) + 32, 0, 255).astype(np.uint8))
        if not has_aligned and paste_back:
            helper.get_inverse_affine(None)
            restored_img = helper.paste_faces_to_input_image(upsample_img=None)
            return helper.cropped_faces, helper.restored_faces, restored_img
        return helper.cropped_faces, helper.restored_faces, None


class ContractMirrorFaceRestoreHelper:
    """A fake ``FaceRestoreHelper`` mirroring the real one. NOT a definition.

    Contract mirror - see ``ContractMirrorGFPGANer``. The method set is the real
    one: `read_image` / `get_face_landmarks_5` / `align_warp_face` /
    `get_inverse_affine` / `add_restored_face` / `paste_faces_to_input_image` /
    `clean_all`, and deliberately NOT `align_wrtk`, which does not exist upstream.
    """

    def __init__(
        self,
        upscale_factor,
        face_size=512,
        crop_ratio=(1, 1),
        det_model="retinaface_resnet50",
        save_ext="png",
        template_3points=False,
        pad_blur=False,
        use_parse=False,
        device=None,
        model_rootpath=None,
    ):
        self.upscale_factor = upscale_factor
        self.face_size = face_size
        self.crop_ratio = crop_ratio
        self.det_model = det_model
        self.device = device
        self.model_rootpath = model_rootpath
        self.use_parse = use_parse
        # `boxes` is what this mirror detects: one full-frame face, expressed in
        # the same [x0, y0, x1, y1, score] shape real `det_faces` entries have.
        self.boxes = [(0.0, 0.0, 32.0, 32.0, 0.99)]
        self.clean_all()

    def clean_all(self):
        self.all_landmarks_5 = []
        self.restored_faces = []
        self.affine_matrices = []
        self.cropped_faces = []
        self.inverse_affine_matrices = []
        self.det_faces = []
        self.pad_input_imgs = []

    def read_image(self, img):
        # Real signature: a BGR ndarray, or a path. Accepting a PIL image here
        # would hide the very conversion bug this module exists to catch.
        if isinstance(img, Image.Image):
            raise TypeError(
                "FaceRestoreHelper.read_image got a PIL image; the real helper "
                "expects a BGR ndarray (see skin_enhancer.pil_to_bgr)"
            )
        self.input_img = img

    def get_face_landmarks_5(
        self,
        only_keep_largest=False,
        only_center_face=False,
        resize=None,
        blur_ratio=0.01,
        eye_dist_threshold=None,
    ):
        h, w = self.input_img.shape[0:2]
        for x0, y0, x1, y1, score in self.boxes:
            if min(x1 - x0, y1 - y0) <= 0:
                continue
            cx, cy = (x0 + x1) / 2.0, (y0 + y1) / 2.0
            self.all_landmarks_5.append(
                np.array(
                    [
                        [cx - 8, cy - 8],
                        [cx + 8, cy - 8],
                        [cx, cy],
                        [cx - 8, cy + 8],
                        [cx + 8, cy + 8],
                    ],
                    dtype=np.float32,
                )
            )
            self.det_faces.append(np.array([x0, y0, x1, y1, score], dtype=np.float32))
        return len(self.all_landmarks_5)

    def align_warp_face(self, save_cropped_path=None, border_mode="constant"):
        # A real affine warp to (face_size, face_size). The mirror centre-crops,
        # which is enough for the adapter tests and keeps the fake honest about
        # the fact that upstream returns a 512x512 BGR ndarray per face.
        h, w = self.input_img.shape[0:2]
        for landmarks in self.all_landmarks_5:
            cx = float(landmarks[2][0])
            cy = float(landmarks[2][1])
            half = min(w, h) // 4
            left, top = int(max(0, cx - half)), int(max(0, cy - half))
            right, bottom = int(min(w, cx + half)), int(min(h, cy + half))
            self.affine_matrices.append(None)
            self.cropped_faces.append(self.input_img[top:bottom, left:right].copy())

    def get_inverse_affine(self, save_inverse_affine_path=None):
        for _ in self.affine_matrices:
            self.inverse_affine_matrices.append(None)

    def add_restored_face(self, face):
        self.restored_faces.append(face)

    def paste_faces_to_input_image(self, save_path=None, upsample_img=None):
        # upscale_factor=1 in every configuration this app builds, so upstream
        # resizes the background by a factor of one - a no-op. The mirror does the
        # same and paints the restored faces straight onto the input copy.
        out = (self.input_img if upsample_img is None else upsample_img).astype(np.uint8).copy()
        for face in self.restored_faces:
            height = min(face.shape[0], out.shape[0])
            width = min(face.shape[1], out.shape[1])
            out[:height, :width] = face[:height, :width]
        return out


class TestStubSignaturesMirrorRealApi:
    """The CI fakes must not be the authority on what the real API looks like."""

    @staticmethod
    def _params_from_signature_literal(literal: str) -> list:
        node = ast.parse(f"def f({literal}): ...").body[0]
        assert isinstance(node, ast.FunctionDef)
        return [arg.arg for arg in node.args.args if arg.arg != "self"]

    def test_mirror_init_signature_matches_the_documented_upstream_one(self):
        """Compared against the literal signature copied out of gfpgan 1.3.8's
        `GFPGANer.__init__`, so this holds even with no torch installed."""
        expected = self._params_from_signature_literal(GFPGANER_INIT_SIGNATURE)
        actual = [name for name in _param_names(ContractMirrorGFPGANer.__init__) if name != "self"]
        assert actual == expected, (
            f"ContractMirrorGFPGANer takes {actual}, upstream takes {expected}"
        )

    def test_mirror_enhance_signature_matches_the_documented_upstream_one(self):
        expected = self._params_from_signature_literal(GFPGANER_ENHANCE_SIGNATURE)
        actual = [name for name in _param_names(ContractMirrorGFPGANer.enhance) if name != "self"]
        assert actual == expected, (
            f"ContractMirrorGFPGANer.enhance takes {actual}, upstream takes {expected}"
        )

    def test_mirror_has_no_apis_that_do_not_exist_upstream(self):
        for invented in ("enhance_model", "to", "face_helper_input"):
            assert not hasattr(ContractMirrorGFPGANer, invented), (
                f"the mirror defines .{invented}(), which upstream GFPGANer does not"
            )
        assert not hasattr(ContractMirrorFaceRestoreHelper, "align_wrtk")

    @pytest.mark.parametrize(
        "module_name",
        ["gfpgan", "facexlib.utils.face_restoration_helper"],
    )
    def test_mirror_matches_the_real_class_whenever_it_is_importable(self, module_name):
        """Where the real packages exist, the mirror is diffed against them rather
        than against a comment. SKIPPED otherwise - see TestSkipIsLoud."""
        module = pytest.importorskip(module_name)

        if module_name == "gfpgan":
            real, mirror = module.GFPGANer, ContractMirrorGFPGANer
            for name in ("__init__", "enhance"):
                real_params = [p for p in _param_names(getattr(real, name)) if p != "self"]
                mirror_params = [p for p in _param_names(getattr(mirror, name)) if p != "self"]
                assert mirror_params == real_params, (
                    f"{name}: mirror takes {mirror_params}, real gfpgan.GFPGANer takes "
                    f"{real_params}. Update the mirror, not the assertion."
                )
        else:
            real = module.FaceRestoreHelper
            real_methods = {
                name
                for name, value in vars(real).items()
                if callable(value) and not name.startswith("__")
            }
            mirror_methods = {
                name
                for name, value in vars(ContractMirrorFaceRestoreHelper).items()
                if callable(value) and not name.startswith("__")
            }
            missing = real_methods - mirror_methods
            assert not missing, (
                f"the mirror is missing {sorted(missing)}; facexlib 0.3.0's "
                "FaceRestoreHelper has them, so a stub can no longer be narrower "
                "than the real class without this failing."
            )


# --------------------------------------------------------------------------- #
# DiffBIR: the contract is the argv, because the CLI is the only real API
# --------------------------------------------------------------------------- #

#: Mirror of the ``inference.py::parse_args`` flags this app passes, checked out
#: at DiffBIR commit 5c2d6c1 (Apache-2.0). The flag *types* matter as much as the
#: names: ``--cleaner_tiled``/``--cldm_tiled`` are ``action="store_true"``, so
#: spelling them ``--cleaner_tiled true`` makes argparse abort with
#: "unrecognized arguments: true" - a failure that would only ever appear on a
#: GPU, hours into a request.
def diffbir_argv_mirror_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("--task", choices=["sr", "face", "denoise", "unaligned_face"])
    parser.add_argument("--version", choices=["v1", "v2", "v2.1", "custom"])
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--upscale", type=float)
    parser.add_argument("--captioner", choices=["none", "llava", "ram"])
    parser.add_argument("--pos_prompt")
    parser.add_argument("--neg_prompt")
    parser.add_argument("--cfg_scale", type=float)
    parser.add_argument("--noise_aug", type=int)
    parser.add_argument("--steps", type=int)
    parser.add_argument("--cleaner_tiled", action="store_true")
    parser.add_argument("--cldm_tiled", action="store_true")
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"])
    parser.add_argument("--precision", choices=["fp32", "fp16", "bf16"])
    parser.add_argument("--seed", type=int)
    parser.add_argument("--n_samples", type=int)
    return parser


def _preset_names():
    """The Flexible preset names, read through the production table.

    Imported lazily so this module's collection does not need `app` to be
    importable before the parametrize list can be built.
    """
    from app.ml.skin_enhancer import FLEXIBLE_PRESETS

    return FLEXIBLE_PRESETS


def _flag_value(argv, flag):
    return argv[argv.index(flag) + 1]


class TestDiffBIRArgvContract:
    """Assert on the argv itself, not on a mock's call record.

    The subprocess is never executed: the whole point is that the flag spelling is
    checkable on a machine with no GPU and no DiffBIR checkout.
    """

    def test_argv_parses_under_a_mirror_of_the_real_parser(self):
        from app.ml.skin_enhancer import build_diffbir_argv

        argv = build_diffbir_argv(
            python_executable="/opt/diffbir-venv/bin/python",
            repo_root=Path("/opt/DiffBIR"),
            input_dir=Path("/tmp/work/in"),
            output_dir=Path("/tmp/work/out"),
            prompt="a prompt",
            guidance_scale=3.0,
            condition_noise=0.2,
        )
        assert Path(argv[0]).name == "python"
        assert Path(argv[1]) == Path("/opt/DiffBIR/inference.py")
        # argv[2:], because Python itself consumes argv[1] (the script path) and
        # argparse only ever sees the flags. That is exactly what DiffBIR's own
        # `parse_args()` receives when `inference.py` is the entrypoint.
        parsed = diffbir_argv_mirror_parser().parse_args(argv[2:])
        assert parsed.task == "unaligned_face"
        assert parsed.version == "v2.1"
        assert parsed.captioner == "none"
        assert parsed.input == "/tmp/work/in"
        assert parsed.output == "/tmp/work/out"
        assert parsed.upscale == 1.0
        assert parsed.cfg_scale == 3.0
        assert parsed.noise_aug == 40
        assert parsed.steps == 10
        assert parsed.cleaner_tiled is True
        assert parsed.cldm_tiled is True
        assert parsed.device == "cuda"
        assert parsed.precision == "fp16"
        assert parsed.seed == 231
        assert parsed.n_samples == 1

    def test_tiled_flags_are_bare_store_true_flags(self):
        """`--cleaner_tiled true` would abort argparse, because `true` then parses as
        an unrecognised positional. The published 8 GB figure is *for tiled
        inference*, so these two flags are not optional."""
        from app.ml.skin_enhancer import build_diffbir_argv

        argv = build_diffbir_argv(
            python_executable="python",
            repo_root=Path("/opt/DiffBIR"),
            input_dir=Path("/tmp/in"),
            output_dir=Path("/tmp/out"),
            prompt="p",
            guidance_scale=3.0,
            condition_noise=0.2,
        )
        for flag in ("--cleaner_tiled", "--cldm_tiled"):
            index = argv.index(flag)
            assert index == len(argv) - 1 or argv[index + 1].startswith("--"), (
                f"{flag} is action='store_true'; the token after it "
                f"({argv[index + 1]!r}) would be parsed as an unexpected positional."
            )

    def test_captioner_is_none_so_only_the_static_prompt_is_used(self):
        """#111 chose a static prompt table with no captioner to protect the 16 GB
        floor and keep CI testable. Against the real implementation that decision
        holds: `--captioner none` instantiates `EmptyCaptioner`, which returns '',
        and `InferenceLoop.run` joins only the non-empty parts, leaving
        `--pos_prompt` as the whole positive prompt. A future reader must not
        'fix' this to the default `llava`, which would add ~16 GB.
        """
        from app.ml.skin_enhancer import build_diffbir_argv

        argv = build_diffbir_argv(
            python_executable="python",
            repo_root=Path("/opt/DiffBIR"),
            input_dir=Path("/tmp/in"),
            output_dir=Path("/tmp/out"),
            prompt="a prompt",
            guidance_scale=3.0,
            condition_noise=0.2,
        )
        assert _flag_value(argv, "--captioner") == "none"
        assert _flag_value(argv, "--pos_prompt") == "a prompt"
        # The negative prompt is DiffBIR's own default, which is a good fit for a
        # portrait enhancer: it penalises "over-smooth" (what `no_make_up` removes)
        # and "painting, illustration, ... 3D render" (what `transform_to_real` is
        # pushing away from). Copied verbatim rather than invented.
        from app.ml.skin_enhancer import DIFFBIR_NEGATIVE_PROMPT

        assert _flag_value(argv, "--neg_prompt") == DIFFBIR_NEGATIVE_PROMPT
        assert "over-smooth" in DIFFBIR_NEGATIVE_PROMPT

    @pytest.mark.parametrize("preset_name", sorted(_preset_names()))
    def test_every_presets_prompt_reaches_pos_prompt_verbatim(self, preset_name):
        from app.ml.skin_enhancer import (
            FLEXIBLE_PRESETS,
            build_diffbir_argv,
            map_condition_noise_to_noise_aug,
            map_skin_detail_to_guidance,
        )

        preset = FLEXIBLE_PRESETS[preset_name]
        argv = build_diffbir_argv(
            python_executable="python",
            repo_root=Path("/opt/DiffBIR"),
            input_dir=Path("/tmp/in"),
            output_dir=Path("/tmp/out"),
            prompt=preset["prompt"],
            guidance_scale=map_skin_detail_to_guidance(80, preset["guidance_scale"]),
            condition_noise=preset["condition_noise"],
        )
        assert _flag_value(argv, "--pos_prompt") == preset["prompt"]
        assert float(_flag_value(argv, "--cfg_scale")) == pytest.approx(
            preset["guidance_scale"]
        )
        assert int(_flag_value(argv, "--noise_aug")) == map_condition_noise_to_noise_aug(
            preset["condition_noise"]
        )

    @pytest.mark.parametrize("skin_detail,expected", [(0, 1.0), (40, 1.5), (80, 3.0), (100, 3.75)])
    def test_skin_detail_maps_onto_cfg_scale(self, skin_detail, expected):
        """Decision 2's contract, expressed in the knob DiffBIR actually has:
        `skin_detail` is `--cfg_scale`, not a diffusers `guidance_scale` kwarg."""
        from app.ml.skin_enhancer import build_diffbir_argv, map_skin_detail_to_guidance

        argv = build_diffbir_argv(
            python_executable="python",
            repo_root=Path("/opt/DiffBIR"),
            input_dir=Path("/tmp/in"),
            output_dir=Path("/tmp/out"),
            prompt="p",
            guidance_scale=map_skin_detail_to_guidance(skin_detail, 3.0),
            condition_noise=0.25,
        )
        assert float(_flag_value(argv, "--cfg_scale")) == pytest.approx(expected)

    @pytest.mark.parametrize(
        "condition_noise,expected", [(0.0, 0), (0.2, 40), (0.25, 50), (0.4, 80), (1.0, 199)]
    )
    def test_condition_noise_maps_onto_the_integer_noise_aug_timestep(
        self, condition_noise, expected
    ):
        """`--noise_aug` is `type=int` and is fed straight into
        `diffusion.q_sample(t=noise_aug)`, with 0 meaning "no condition noise at
        all". #111's preset column is a 0..1 creativity fraction, so it is rescaled
        linearly onto DiffBIR's own webui bounds (0..199).

        Honest caveat, repeated in the production comment: the *endpoints* are
        upstream's, but where each #111 preset lands inside that range was chosen
        by a linear rescale, not by looking at output. It is unverified without a
        GPU.
        """
        from app.ml.skin_enhancer import DIFFBIR_MAX_NOISE_AUG, map_condition_noise_to_noise_aug

        assert map_condition_noise_to_noise_aug(condition_noise) == expected
        assert DIFFBIR_MAX_NOISE_AUG == 199
        # 0 must stay 0: DiffBIR short-circuits `if noise_aug > 0`, so any positive
        # value turns the feature on and 0.0 in the preset table has to mean "off".
        assert map_condition_noise_to_noise_aug(0.0) == 0

    def test_argv_never_leaks_the_repository_path_when_it_is_unset(self):
        """An unconfigured operator-supplied path must not become an argv entry
        pointing somewhere plausible; the loader refuses before argv is built."""
        from app.ml.skin_enhancer import make_diffbir_loader

        with pytest.raises(ValueError) as exc:
            make_diffbir_loader("diffbir")()
        message = str(exc.value)
        assert "DIFFBIR_REPO_PATH" in message
        assert "inference.py" in message or "not" in message


class TestDiffBIRRepoPathContract:
    """A missing operator-supplied checkout degrades; it never fabricates output."""

    def _with_repo_path(self, monkeypatch, value):
        import app.ml.skin_enhancer as skin_mod

        # Patched on the settings *instance*, not the class: pydantic resolves a
        # field to the value captured at construction time, so a class-level patch
        # reads back as the original empty string and the test would pass or fail
        # for the wrong reason.
        monkeypatch.setattr(skin_mod.settings, "DIFFBIR_REPO_PATH", value)
        assert skin_mod.settings.DIFFBIR_REPO_PATH == value

    def test_unset_repo_path_raises_naming_the_setting(self, monkeypatch):
        from app.ml.skin_enhancer import make_diffbir_loader

        self._with_repo_path(monkeypatch, "")
        with pytest.raises(ValueError) as exc:
            make_diffbir_loader("diffbir")()
        assert "DIFFBIR_REPO_PATH" in str(exc.value)

    def test_repo_path_pointing_at_nothing_raises_naming_the_path(self, monkeypatch, tmp_path):
        from app.ml.skin_enhancer import make_diffbir_loader

        missing = tmp_path / "not-a-checkout"
        self._with_repo_path(monkeypatch, str(missing))
        with pytest.raises(ValueError) as exc:
            make_diffbir_loader("diffbir")()
        assert "DIFFBIR_REPO_PATH" in str(exc.value)
        assert str(missing) in str(exc.value)

    def test_repo_path_without_inference_py_raises(self, monkeypatch, tmp_path):
        from app.ml.skin_enhancer import make_diffbir_loader

        self._with_repo_path(monkeypatch, str(tmp_path))
        with pytest.raises(ValueError) as exc:
            make_diffbir_loader("diffbir")()
        assert "inference.py" in str(exc.value)

    def test_unset_repo_path_degrades_the_endpoint_and_writes_nothing(
        self, client, monkeypatch, stub_storage
    ):
        """End to end: the loader's refusal becomes the labeled LOAD_FAILED envelope
        at HTTP 200, and no object and no catalog row are produced. A Creative or
        Flexible request against an unconfigured deployment must never answer with
        invented pixels."""
        from app.ml.contracts import DegradedReason
        from app.ml.guard import vram_guard
        from app.ml.registry import model_registry
        from app.models import MediaAsset

        from .test_skin_enhancer import png_bytes

        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(),
            "content_type": "image/png",
        }
        self._with_repo_path(monkeypatch, "")

        from .test_skin_enhancer import NO_GPU, _gpu

        monkeypatch.setattr(vram_guard, "get_gpu_info", lambda device=0: _gpu(24.0))
        # Run the *real* loader closure, but do not let the registry cache the
        # result - the closure is expected to raise, and a cached success from an
        # earlier test would make this pass for the wrong reason.
        monkeypatch.setattr(
            model_registry, "load_model", lambda mid, **kw: kw["loader_handle"]()
        )
        before = len(stub_storage["uploaded"])

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png", "mode": "creative"})
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert "DIFFBIR_REPO_PATH" in body["message"]
        assert "filename" not in body and "url" not in body
        assert len(stub_storage["uploaded"]) == before, "nothing may be written to storage"
        assert isinstance(MediaAsset, type)


class TestDiffBIRStagingIntegration:
    """How crops go in and results come back out.

    `subprocess.run` is replaced, so nothing is executed and no DiffBIR checkout is
    needed. What is asserted is the contract the real CLI imposes: the crop must be
    on disk in `--input` *before* the call, the process must run with the repo root
    as its working directory (its `OmegaConf.load("configs/inference/swinir.yaml")`
    paths are CWD-relative), and the result is read back as `<stem>_0.png`.
    """

    @pytest.fixture()
    def stub_subprocess(self, monkeypatch):
        calls = []
        state = {"staged": [], "written": {}}

        def fake_run(argv, **kwargs):
            in_dir = Path(argv[argv.index("--input") + 1])
            out_dir = Path(argv[argv.index("--output") + 1])
            # Record what was actually on disk at call time: this is the assertion
            # that the crop is staged *in*, not merely referenced.
            state["staged"] = sorted(p.name for p in in_dir.iterdir())
            calls.append({"argv": list(argv), "kwargs": kwargs, "out_dir": out_dir})
            stem = Path(state["staged"][0]).stem
            result = out_dir / f"{stem}_0.png"
            Image.new("RGB", (24, 24), (7, 200, 7)).save(result)
            state["written"][stem] = result
            return types.SimpleNamespace(returncode=0, stdout="done!", stderr="")

        monkeypatch.setattr("app.ml.skin_enhancer.subprocess.run", fake_run)
        return types.SimpleNamespace(calls=calls, state=state)

    def _engine(self, monkeypatch, tmp_path, stub_subprocess, **overrides):
        import app.ml.skin_enhancer as skin_mod

        repo = tmp_path / "DiffBIR"
        (repo / "configs" / "inference").mkdir(parents=True)
        (repo / "inference.py").write_text("# stub\n", encoding="utf-8")

        defaults = {
            "repo_path": str(repo),
            "python_executable": "/opt/diffbir-venv/bin/python",
            "timeout_seconds": 300.0,
        }
        defaults.update(overrides)
        return skin_mod.DiffBIRFaceEngine(**defaults), repo

    def test_crop_is_staged_in_and_result_is_read_back(self, monkeypatch, tmp_path, stub_subprocess):
        engine, repo = self._engine(monkeypatch, tmp_path, stub_subprocess)
        crop = Image.new("RGB", (24, 24), (10, 20, 30))

        out = engine.restore_face(
            crop, prompt="a prompt", guidance_scale=3.0, condition_noise=0.2, num_inference_steps=10
        )

        assert stub_subprocess.calls, "the DiffBIR CLI was never invoked"
        call = stub_subprocess.calls[0]
        # CWD must be the repo root: inference.py loads its configs by CWD-relative
        # path, so any other cwd is a FileNotFoundError on a real machine.
        assert Path(call["kwargs"]["cwd"]) == repo
        assert call["kwargs"]["timeout"] == 300.0
        # A real PNG of the crop, on disk, under --input, before the call.
        assert len(stub_subprocess.state["staged"]) == 1
        assert stub_subprocess.state["staged"][0].endswith(".png")
        # The result is a PIL image of the crop's size, ready to paste back.
        assert isinstance(out, Image.Image)
        assert out.size == crop.size
        assert out.getpixel((0, 0)) == (7, 200, 7)

    def test_nonzero_exit_is_an_error_not_a_silent_empty_crop(self, monkeypatch, tmp_path):
        """A crashed subprocess must not yield the source crop back: that would look
        like "enhancement ran and changed nothing", which is a lie."""
        import app.ml.skin_enhancer as skin_mod

        repo = tmp_path / "DiffBIR"
        (repo / "configs" / "inference").mkdir(parents=True)
        (repo / "inference.py").write_text("# stub\n", encoding="utf-8")
        engine = skin_mod.DiffBIRFaceEngine(
            repo_path=str(repo), python_executable="python", timeout_seconds=5.0
        )

        def failing_run(argv, **kwargs):
            return types.SimpleNamespace(
                returncode=1, stdout="", stderr="ModuleNotFoundError: torchsde\n"
            )

        monkeypatch.setattr("app.ml.skin_enhancer.subprocess.run", failing_run)

        with pytest.raises(RuntimeError) as exc:
            engine.restore_face(
                Image.new("RGB", (24, 24)),
                prompt="p",
                guidance_scale=3.0,
                condition_noise=0.2,
                num_inference_steps=10,
            )
        assert "torchsde" in str(exc.value)

    def test_missing_output_file_is_an_error(self, monkeypatch, tmp_path):
        """DiffBIR exiting 0 without writing `<stem>_0.png` still means there is no
        result. Fabricating one - or passing the input crop through - is exactly the
        class of lie #111 decision 8 forbids."""
        import app.ml.skin_enhancer as skin_mod

        repo = tmp_path / "DiffBIR"
        (repo / "configs" / "inference").mkdir(parents=True)
        (repo / "inference.py").write_text("# stub\n", encoding="utf-8")
        engine = skin_mod.DiffBIRFaceEngine(
            repo_path=str(repo), python_executable="python", timeout_seconds=5.0
        )
        monkeypatch.setattr(
            "app.ml.skin_enhancer.subprocess.run",
            lambda argv, **kw: types.SimpleNamespace(returncode=0, stdout="", stderr=""),
        )

        with pytest.raises(RuntimeError) as exc:
            engine.restore_face(
                Image.new("RGB", (24, 24)),
                prompt="p",
                guidance_scale=3.0,
                condition_noise=0.2,
                num_inference_steps=10,
            )
        assert "_0.png" in str(exc.value)

    def test_timeout_is_always_passed_so_a_hang_cannot_hold_the_inference_lock(self):
        """INFERENCE_LOCK serialises every inference request in the process. A
        subprocess with no timeout would hold it indefinitely on a wedged GPU.

        Asserted on `restore_faces` rather than on `restore_face`, because the single-crop
        entry point is now a one-line delegation to the batch path - the subprocess lives
        there. The second assertion is what keeps that delegation honest: `restore_face`
        has to route through the method that carries the timeout, or a future edit could
        give the one-crop path its own unguarded `subprocess.run`.
        """
        import app.ml.skin_enhancer as skin_mod

        import inspect as _inspect

        batch_source = _inspect.getsource(skin_mod.DiffBIRFaceEngine.restore_faces)
        assert "timeout=" in batch_source
        assert "subprocess.run(" in batch_source

        single_source = _inspect.getsource(skin_mod.DiffBIRFaceEngine.restore_face)
        assert "subprocess.run(" not in single_source, (
            "restore_face must not have grown a second, unguarded subprocess call"
        )
        assert "restore_faces(" in single_source

    def test_full_route_runs_through_the_real_diffbir_adapter(
        self, client, monkeypatch, stub_storage
    ):
        """The route, the executor's crop/paste loop and the real `DiffBIRFaceEngine`
        together - with only `subprocess.run` replaced.

        The gap this closes: every other test either used a duck-typed
        `FakeFaceEngine` (so the adapter was never involved) or poked the adapter
        directly (so the route's parameter mapping was never involved). This runs
        both, which is the only way a mismatch between `resolve_engine_params` and
        `build_diffbir_argv` could ever be caught.
        """
        import app.ml.skin_enhancer as skin_mod
        from app.ml.guard import vram_guard

        from .test_skin_engine_contracts import ContractMirrorFaceRestoreHelper
        from .test_skin_enhancer import _gpu, gradient_png, png_bytes

        repo = Path("/opt/DiffBIR")
        engine = skin_mod.DiffBIRFaceEngine(
            repo_path=str(repo),
            python_executable="/opt/diffbir-venv/bin/python",
            timeout_seconds=30.0,
        )
        # The detector is the only thing the adapter would import; replace it with
        # the mirror so no facexlib/torch is needed. `subprocess.run` is replaced
        # below, so no DiffBIR checkout is needed either.
        engine._face_helper = ContractMirrorFaceRestoreHelper(1)

        observed: dict = {}

        def fake_run(argv, **kwargs):
            in_dir = Path(argv[argv.index("--input") + 1])
            out_dir = Path(argv[argv.index("--output") + 1])
            stem = sorted(p.stem for p in in_dir.glob("*.png"))[0]
            observed["argv"] = list(argv)
            observed["cwd"] = Path(kwargs["cwd"])
            observed["timeout"] = kwargs["timeout"]
            Image.new("RGB", (32, 32), (1, 2, 3)).save(out_dir / f"{stem}_0.png")
            return types.SimpleNamespace(returncode=0, stdout="done!", stderr="")

        monkeypatch.setattr("app.ml.skin_enhancer.subprocess.run", fake_run)
        monkeypatch.setattr(vram_guard, "get_gpu_info", lambda device=0: _gpu(24.0))
        monkeypatch.setattr(
            skin_mod.model_registry, "load_model", lambda mid, **kw: engine
        )

        stub_storage["uploaded"]["portrait.png"] = {
            "data": gradient_png(96, 96),
            "content_type": "image/png",
        }
        res = client.post(
            "/api/skin-enhance",
            json={
                "image_path": "portrait.png",
                "mode": "flexible",
                "preset": "no_make_up",
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["engine"] == "diffbir"
        assert body["faces_enhanced"] == 1
        assert body["face_boxes"] == [[0, 0, 32, 32]]
        assert body["filename"] in stub_storage["uploaded"]

        # The argv really carried this preset's prompt, the mapped guidance scale
        # and the mapped condition noise, and the process ran in the repo root.
        from app.ml.skin_enhancer import FLEXIBLE_PRESETS

        preset = FLEXIBLE_PRESETS["no_make_up"]
        assert _flag_value(observed["argv"], "--pos_prompt") == preset["prompt"]
        assert float(_flag_value(observed["argv"], "--cfg_scale")) == pytest.approx(
            preset["guidance_scale"]
        )
        assert int(_flag_value(observed["argv"], "--noise_aug")) == 60
        assert _flag_value(observed["argv"], "--captioner") == "none"
        assert _flag_value(observed["argv"], "--task") == "unaligned_face"
        assert observed["cwd"] == repo
        assert observed["timeout"] == 30.0

    def test_a_crashed_subprocess_degrades_the_route_and_writes_nothing(
        self, client, monkeypatch, stub_storage
    ):
        """The subprocess failing is a *load* failure as far as the route is
        concerned, and it must not produce an object or a catalog row."""
        import app.ml.skin_enhancer as skin_mod
        from app.ml.contracts import DegradedReason
        from app.ml.guard import vram_guard

        from .test_skin_enhancer import _gpu, png_bytes
        from .test_skin_engine_contracts import ContractMirrorFaceRestoreHelper

        engine = skin_mod.DiffBIRFaceEngine(
            repo_path="/opt/DiffBIR",
            python_executable="python",
            timeout_seconds=5.0,
        )
        engine._face_helper = ContractMirrorFaceRestoreHelper(1)
        monkeypatch.setattr(
            "app.ml.skin_enhancer.subprocess.run",
            lambda argv, **kw: types.SimpleNamespace(
                returncode=1, stdout="", stderr="ModuleNotFoundError: No module named 'lpips'"
            ),
        )
        monkeypatch.setattr(vram_guard, "get_gpu_info", lambda device=0: _gpu(24.0))
        monkeypatch.setattr(skin_mod.model_registry, "load_model", lambda mid, **kw: engine)

        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(),
            "content_type": "image/png",
        }
        before = len(stub_storage["uploaded"])
        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "mode": "creative"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert "lpips" in body["message"], (
            "the operator needs the subprocess's stderr, not 'exit status 1'"
        )
        assert "filename" not in body
        assert len(stub_storage["uploaded"]) == before


#: The colour the batch stub writes back for a staged crop. Deliberately *not* the
#: input colour: an implementation that returned the crops it was handed - or skipped
#: the subprocess entirely - would pass an order test that echoed its input.
def _echoed(colour):
    return tuple((channel + 1) % 256 for channel in colour)


class TestDiffBIRBatchRestore:
    """N face crops, ONE subprocess.

    Why this is a separate class from `TestDiffBIRStagingIntegration`: that class
    pins the single-crop contract, and a per-face `restore_face` still has to satisfy
    it. The batch path is a different claim - DiffBIR's `--input` is a *folder*
    (`load_lq` globs it with `sorted(os.listdir(...))`, keeping `.png/.jpg/.jpeg`) and
    `UnAlignedBFRInferenceLoop.save` writes one `<stem>_0.png` per input - so every
    crop can go into one staging directory and be restored by one process, paying the
    SwinIR + conditional-diffusion + SD 2.1 load once instead of N times.

    The stub stands in for `inference.py`: it reads the staging directory *as it found
    it* and writes one output per staged input, which is what makes the assertions
    below about the filesystem rather than about a mock's call record.
    """

    #: One crop per colour, so a result's position in the returned list is
    #: identifiable from the result itself.
    CROP_COLOURS = ((10, 0, 0), (0, 20, 0), (0, 0, 30), (40, 60, 80))

    @pytest.fixture()
    def echo_subprocess(self, monkeypatch):
        """`inference.py`, mirrored: read every staged crop, write `<stem>_0.png` per
        input, in *reverse* order.

        Reverse on purpose. A real run writes in input order, so a production read-back
        that went by directory order rather than by stem would pass against a
        same-order stub and mis-pair faces on real hardware. Each output carries its own
        input's colour (shifted by `_echoed`), so ordering is checked against content.
        """
        calls = []

        def fake_run(argv, **kwargs):
            in_dir = Path(argv[argv.index("--input") + 1])
            out_dir = Path(argv[argv.index("--output") + 1])
            staged = sorted(p for p in in_dir.iterdir() if p.suffix == ".png")
            calls.append(
                {
                    "argv": list(argv),
                    "kwargs": kwargs,
                    "input_dir": in_dir,
                    "output_dir": out_dir,
                    "staged": [p.name for p in staged],
                    "colours": [_read_solid_colour(p) for p in staged],
                }
            )
            for staged_file in reversed(staged):
                with Image.open(staged_file) as src:
                    src.load()
                    Image.new("RGB", src.size, _echoed(src.getpixel((0, 0)))).save(
                        out_dir / f"{staged_file.stem}_0.png"
                    )
            return types.SimpleNamespace(returncode=0, stdout="done!", stderr="")

        monkeypatch.setattr("app.ml.skin_enhancer.subprocess.run", fake_run)
        return types.SimpleNamespace(calls=calls)

    def _engine(self, tmp_path, **overrides):
        import app.ml.skin_enhancer as skin_mod

        repo = tmp_path / "DiffBIR"
        (repo / "configs" / "inference").mkdir(parents=True)
        (repo / "inference.py").write_text("# stub\n", encoding="utf-8")
        kwargs = {
            "repo_path": str(repo),
            "python_executable": "/opt/diffbir-venv/bin/python",
            "timeout_seconds": 300.0,
        }
        kwargs.update(overrides)
        return skin_mod.DiffBIRFaceEngine(**kwargs), repo

    def _crops(self):
        return [Image.new("RGB", (24, 24), colour) for colour in self.CROP_COLOURS]

    def test_four_crops_cost_exactly_one_subprocess_invocation(self, tmp_path, echo_subprocess):
        """The load count is the whole point: each DiffBIR invocation reloads SwinIR x2,
        ControlLDM, SD 2.1 and the diffusion schedule, so an N-face group shot must cost
        one, not N. Asserted on the staging directory as it was found at call time and
        on the argv's single `--input`/`--output` pair - not on a mock's call count
        alone, which would also pass if only the first crop had been staged.
        """
        engine, repo = self._engine(tmp_path)
        crops = self._crops()

        out = engine.restore_faces(
            crops,
            prompt="a prompt",
            guidance_scale=3.0,
            condition_noise=0.2,
            num_inference_steps=10,
        )

        assert len(echo_subprocess.calls) == 1, (
            f"expected one DiffBIR process for {len(crops)} faces, got "
            f"{len(echo_subprocess.calls)}; each one is another model load"
        )
        call = echo_subprocess.calls[0]
        # All N crops are on disk, as real PNGs, under the one --input folder, before
        # the call - and the stems are unique, so no two can read back the same file.
        assert len(call["staged"]) == len(crops)
        assert len(set(call["staged"])) == len(crops)
        assert all(name.endswith(".png") for name in call["staged"])
        # The folders in argv are the folders that were actually written and read.
        assert call["argv"].count("--input") == 1 and call["argv"].count("--output") == 1
        assert Path(call["argv"][call["argv"].index("--input") + 1]) == call["input_dir"]
        assert Path(call["argv"][call["argv"].index("--output") + 1]) == call["output_dir"]
        # CWD-is-repo-root and the timeout survive batching unchanged: inference.py
        # loads its configs by CWD-relative path, and a hang would hold INFERENCE_LOCK.
        assert Path(call["kwargs"]["cwd"]) == repo
        assert call["kwargs"]["timeout"] == 300.0
        assert len(out) == len(crops)

    def test_results_come_back_in_the_order_the_crops_went_in(
        self, tmp_path, echo_subprocess
    ):
        """The executor pairs results with boxes positionally, so a reversed result list
        would paste every face but one onto the wrong face. The stub writes its outputs
        in reverse order and tags each with its own input's colour, so this fails both
        if the read-back follows write order and if the results are returned reversed.
        """
        engine, _repo = self._engine(tmp_path)
        crops = self._crops()

        out = engine.restore_faces(
            crops,
            prompt="a prompt",
            guidance_scale=3.0,
            condition_noise=0.2,
            num_inference_steps=10,
        )

        assert [image.getpixel((0, 0)) for image in out] == [
            _echoed(colour) for colour in self.CROP_COLOURS
        ]
        # The staged directory's sorted order is the order the crops went in, which
        # matters because upstream globs with `sorted(os.listdir(...))`.
        assert echo_subprocess.calls[0]["staged"] == sorted(
            echo_subprocess.calls[0]["staged"]
        )
        assert echo_subprocess.calls[0]["colours"] == list(self.CROP_COLOURS)

    def test_one_missing_output_file_fails_the_batch_rather_than_shortening_it(
        self, tmp_path, monkeypatch
    ):
        """DiffBIR exiting 0 without writing every `<stem>_0.png` still means there is
        no result for that face. Returning the rest would shift every later face's
        image onto the previous face's box - a silent, wrong-image bug - so this is an
        error naming the file that is absent, not a short list.
        """
        engine, _repo = self._engine(tmp_path)
        seen: list = []

        def fake_run(argv, **kwargs):
            in_dir = Path(argv[argv.index("--input") + 1])
            out_dir = Path(argv[argv.index("--output") + 1])
            staged = sorted(p for p in in_dir.iterdir() if p.suffix == ".png")
            seen.extend(p.stem for p in staged)
            for staged_file in staged[1:]:  # the first crop gets no output file
                with Image.open(staged_file) as src:
                    src.load()
                    Image.new("RGB", src.size, _echoed(src.getpixel((0, 0)))).save(
                        out_dir / f"{staged_file.stem}_0.png"
                    )
            return types.SimpleNamespace(returncode=0, stdout="done!", stderr="")

        monkeypatch.setattr("app.ml.skin_enhancer.subprocess.run", fake_run)

        with pytest.raises(RuntimeError) as exc:
            engine.restore_faces(
                self._crops(),
                prompt="p",
                guidance_scale=3.0,
                condition_noise=0.2,
                num_inference_steps=10,
            )
        message = str(exc.value)
        assert f"{seen[0]}_0.png" in message, "the absent output file must be named"
        assert "1 of the 4" in message, f"the count must say how many are missing: {message}"

    def test_restore_face_is_the_batch_of_one(self, tmp_path, echo_subprocess):
        """The single-crop entry point stays, and it stays a *real* one: same staging,
        same argv, one process, same error paths. `TestDiffBIRStagingIntegration` keeps
        pinning that from the outside."""
        engine, repo = self._engine(tmp_path)
        crop = Image.new("RGB", (24, 24), (10, 20, 30))

        out = engine.restore_face(
            crop, prompt="p", guidance_scale=3.0, condition_noise=0.2, num_inference_steps=10
        )

        assert len(echo_subprocess.calls) == 1
        call = echo_subprocess.calls[0]
        assert call["staged"] == [call["staged"][0]]
        assert Path(call["kwargs"]["cwd"]) == repo
        assert out.size == crop.size
        assert out.getpixel((0, 0)) == _echoed(crop.getpixel((0, 0)))

    def test_an_empty_crop_list_costs_no_process_at_all(self, tmp_path, echo_subprocess):
        """Defensive: a zero-crop batch must not launch DiffBIR just to have it write
        nothing. The executor cannot reach this (it refuses `no_face_detected` first),
        so it is pinned as a property of the method rather than as route behaviour."""
        engine, _repo = self._engine(tmp_path)

        assert (
            engine.restore_faces(
                [],
                prompt="p",
                guidance_scale=3.0,
                condition_noise=0.2,
                num_inference_steps=10,
            )
            == []
        )
        assert echo_subprocess.calls == []

    def test_the_batch_still_refuses_missing_and_unexpected_parameters(
        self, tmp_path, echo_subprocess
    ):
        """The parameter contract is unchanged by batching: without a prompt, a guidance
        scale and a condition noise there is no argv to build, and an unknown key is a
        mapping bug in `resolve_engine_params` rather than something to forward."""
        engine, _repo = self._engine(tmp_path)

        with pytest.raises(ValueError) as missing:
            engine.restore_faces(self._crops(), prompt="p")
        assert "guidance_scale" in str(missing.value)

        with pytest.raises(ValueError) as unexpected:
            engine.restore_faces(
                self._crops(),
                prompt="p",
                guidance_scale=3.0,
                condition_noise=0.2,
                num_inference_steps=10,
                weight=0.5,
            )
        assert "weight" in str(unexpected.value)
        assert echo_subprocess.calls == [], "a bad parameter set must not launch DiffBIR"

    def test_a_group_shot_through_the_route_is_one_process(
        self, client, monkeypatch, stub_storage, echo_subprocess
    ):
        """The route, the executor's dispatch and the real `DiffBIRFaceEngine` together,
        with only `subprocess.run` replaced.

        This is the assertion that matters end to end: three detected faces, one
        DiffBIR process, three results, all three faces visibly restored and every
        background pixel untouched (#111 decision 4).
        """
        import app.ml.skin_enhancer as skin_mod
        from app.ml.guard import vram_guard
        from app.ml.skin_enhancer import CREATIVE_BASE_GUIDANCE, DEFAULT_SKIN_DETAIL

        from .test_skin_enhancer import _gpu, gradient_png

        engine = skin_mod.DiffBIRFaceEngine(
            repo_path="/opt/DiffBIR",
            python_executable="/opt/diffbir-venv/bin/python",
            timeout_seconds=30.0,
        )
        helper = ContractMirrorFaceRestoreHelper(1)
        # Three faces, in detection order, none overlapping.
        helper.boxes = [(0.0, 0.0, 32.0, 32.0, 0.99), (32.0, 32.0, 64.0, 64.0, 0.99),
                        (64.0, 64.0, 96.0, 96.0, 0.99)]
        engine._face_helper = helper

        monkeypatch.setattr(vram_guard, "get_gpu_info", lambda device=0: _gpu(24.0))
        monkeypatch.setattr(skin_mod.model_registry, "load_model", lambda mid, **kw: engine)

        raw = gradient_png(96, 96)
        stub_storage["uploaded"]["portrait.png"] = {"data": raw, "content_type": "image/png"}
        res = client.post(
            "/api/skin-enhance",
            json={"image_path": "portrait.png", "mode": "creative", "skin_detail": 40},
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["engine"] == "diffbir"
        assert body["faces_enhanced"] == 3
        assert body["face_boxes"] == [[0, 0, 32, 32], [32, 32, 64, 64], [64, 64, 96, 96]]
        assert body["faces_skipped"] == 0

        assert len(echo_subprocess.calls) == 1, (
            f"three faces cost {len(echo_subprocess.calls)} DiffBIR loads; batching is "
            "the whole point of restore_faces"
        )
        call = echo_subprocess.calls[0]
        assert len(call["staged"]) == 3
        assert Path(call["kwargs"]["cwd"]) == Path("/opt/DiffBIR")
        assert call["kwargs"]["timeout"] == 30.0
        # The argv still carries this request's mapped guidance scale.
        assert float(call["argv"][call["argv"].index("--cfg_scale") + 1]) == pytest.approx(
            CREATIVE_BASE_GUIDANCE * 40 / DEFAULT_SKIN_DETAIL
        )

        out = np.array(
            Image.open(io.BytesIO(stub_storage["uploaded"][body["filename"]]["data"])).convert("RGB")
        )
        src = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
        mask = np.ones(src.shape[:2], dtype=bool)
        for x0, y0, x1, y1 in body["face_boxes"]:
            mask[y0:y1, x0:x1] = False
        assert np.array_equal(out[mask], src[mask]), "background pixels changed"
        for x0, y0, x1, y1 in body["face_boxes"]:
            assert not np.array_equal(out[y0 + 1 : y1 - 1, x0 + 1 : x1 - 1], src[y0 + 1 : y1 - 1, x0 + 1 : x1 - 1]), (
                f"the face at {(x0, y0, x1, y1)} came back unenhanced; the batch results "
                "were mis-paired with the boxes"
            )


def _read_solid_colour(path) -> tuple:
    """The top-left pixel of an image on disk, via PIL. Keeps the stubs from reaching
    into numpy for a single value."""
    with Image.open(path) as opened:
        opened.load()
        return opened.convert("RGB").getpixel((0, 0))


# --------------------------------------------------------------------------- #
# PIL <-> BGR conversion: the conversion the real API forces on us
# --------------------------------------------------------------------------- #


class TestGfpganRestoreHonesty:
    """`enhance()` can return a well-formed 3-tuple that restored nothing.

    `GFPGANer.enhance` returns `(cropped_faces, restored_faces, restored_img)` on
    every path. When its own re-detection inside the crop finds no face,
    `cropped_faces` is empty and `restored_img` is the input crop verbatim - a
    plausible-looking PIL image that nothing happened to. Accepting it would make
    the endpoint report `faces_enhanced: 1` for a face that was never restored,
    which is the same class of lie #111 decision 8 rules out.
    """

    def _engine_returning(self, result):
        from app.ml.skin_enhancer import GFPGANFaceEngine

        restorer = types.SimpleNamespace(
            face_helper=ContractMirrorFaceRestoreHelper(1),
            enhance=lambda *a, **k: result,
        )
        return GFPGANFaceEngine(restorer)

    def test_empty_3tuple_is_refused(self):
        empty = np.zeros((8, 8, 3), dtype=np.uint8)
        engine = self._engine_returning(([], [], empty))
        with pytest.raises(ValueError) as exc:
            engine.restore_face(Image.new("RGB", (8, 8)))
        assert "restored nothing" in str(exc.value)

    def test_none_pasted_back_image_is_refused(self):
        engine = self._engine_returning((["a"], ["b"], None))
        with pytest.raises(ValueError) as exc:
            engine.restore_face(Image.new("RGB", (8, 8)))
        assert "pasted-back image" in str(exc.value)

    def test_non_tuple_return_is_refused(self):
        """The first cut did `isinstance(restored, Image.Image)` on the *tuple*,
        which raised "Unrecognized GFPGAN output type: tuple" on every Faithful
        request. The mirror is what makes that shape visible in CI."""
        engine = self._engine_returning(Image.new("RGB", (8, 8)))
        with pytest.raises(ValueError) as exc:
            engine.restore_face(Image.new("RGB", (8, 8)))
        assert "3-tuple" in str(exc.value)

    def test_a_real_3tuple_is_accepted(self):
        bgr = np.zeros((8, 8, 3), dtype=np.uint8)
        bgr[..., 0] = 200  # B channel
        engine = self._engine_returning((["crop"], ["restored"], bgr))
        out = engine.restore_face(Image.new("RGB", (8, 8)))
        assert isinstance(out, Image.Image)
        assert out.size == (8, 8)
        # BGR in means RGB out: the blue-heavy array must come back blue-heavy in
        # PIL's channel order, i.e. low in R.
        assert out.getpixel((0, 0))[2] > out.getpixel((0, 0))[0]


class TestPilBgrConversion:
    def test_pil_to_bgr_reverses_channels(self):
        from app.ml.skin_enhancer import pil_to_bgr

        rgb = np.zeros((2, 2, 3), dtype=np.uint8)
        rgb[..., 0] = 10  # R
        rgb[..., 1] = 20  # G
        rgb[..., 2] = 30  # B
        bgr = pil_to_bgr(Image.fromarray(rgb))
        assert bgr.tolist() == [[[30, 20, 10]] * 2] * 2

    def test_bgr_to_pil_round_trips_without_a_channel_swap(self):
        from app.ml.skin_enhancer import bgr_to_pil, pil_to_bgr

        rng = np.random.RandomState(11)
        rgb = rng.randint(0, 256, (9, 7, 3)).astype(np.uint8)
        out = bgr_to_pil(pil_to_bgr(Image.fromarray(rgb)))
        assert np.array_equal(np.asarray(out), rgb), (
            "a silent R/B swap is the classic way this conversion goes wrong; the "
            "round trip must be exact"
        )

    def test_converted_arrays_are_contiguous(self):
        """`arr[:, :, ::-1]` is a negative-stride view. `Image.fromarray` and
        `cv2` both reject it, so the copy is mandatory, not defensive style."""
        from app.ml.skin_enhancer import bgr_to_pil, pil_to_bgr

        rgb = np.zeros((4, 4, 3), dtype=np.uint8)
        bgr = pil_to_bgr(Image.fromarray(rgb))
        assert bgr.flags["C_CONTIGUOUS"], "PIL->BGR must return a C-contiguous array"
        bgr_to_pil(bgr)  # must not raise
