import os
import shutil
import tempfile
import uuid
import logging
from typing import Generator
from pathlib import Path

logger = logging.getLogger(__name__)

class ScratchpadFileManager:
    def __init__(self, base_dir: str = None):
        if base_dir:
            self.base_dir = Path(base_dir)
        else:
            self.base_dir = Path(tempfile.gettempdir()) / "fusionclip_scratchpad"
        
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Initialized scratchpad at: {self.base_dir}")

    def get_temp_path(self, suffix: str = "") -> Path:
        """Generate a random temporary path within the scratchpad."""
        filename = f"{uuid.uuid4().hex}{suffix}"
        return self.base_dir / filename

    def clean_all(self):
        """Clean all files in the scratchpad directory."""
        try:
            for item in self.base_dir.iterdir():
                if item.is_file():
                    item.unlink()
                elif item.is_dir():
                    shutil.rmtree(item)
            logger.info("Successfully cleaned scratchpad directory.")
        except Exception as e:
            logger.error(f"Failed to clean scratchpad: {e}")

    def remove_path(self, path: Path) -> bool:
        """Remove a specific path if it exists inside the scratchpad."""
        try:
            # Prevent directory traversal attacks
            resolved_path = Path(path).resolve()
            resolved_base = self.base_dir.resolve()
            
            if resolved_base in resolved_path.parents or resolved_path == resolved_base:
                if resolved_path.exists():
                    if resolved_path.is_file():
                        resolved_path.unlink()
                    elif resolved_path.is_dir():
                        shutil.rmtree(resolved_path)
                    return True
            else:
                logger.warning(f"Unsafe path removal skipped: {path}")
        except Exception as e:
            logger.error(f"Failed to remove path {path}: {e}")
        return False

# Global scratchpad singleton
scratchpad = ScratchpadFileManager()
