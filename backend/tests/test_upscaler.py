import pytest
import numpy as np
from PIL import Image
from app.upscaler import (
    calculate_tile_size,
    generate_feather_mask,
    default_mock_process_tile,
    TileUpscaler
)

def test_calculate_tile_size():
    # Low VRAM yields 512
    assert calculate_tile_size(2000, 2000, 6.0) == 512
    # Medium VRAM yields 768
    assert calculate_tile_size(2000, 2000, 10.0) == 768
    # High VRAM yields 1024
    assert calculate_tile_size(2000, 2000, 16.0) == 1024
    
    # If image dimensions are smaller than Calculated Size, cap at next multiple of 64
    assert calculate_tile_size(100, 200, 16.0) == 256

def test_generate_feather_mask():
    # 10x10 tile helper
    mask = generate_feather_mask(
        width=10,
        height=10,
        feather_px=4,
        left_overlap=True,
        right_overlap=False,
        top_overlap=False,
        bottom_overlap=False
    )
    # Left edge should grow from 0.0 to 1.0 (ramp from index 0 to 4)
    # Right edge has no overlap so it should be constant 1.0
    assert mask[5, 0] == 0.0
    assert mask[5, 4] == 1.0
    assert mask[5, 9] == 1.0
    
    # Top and left overlap
    mask2 = generate_feather_mask(
        width=10,
        height=10,
        feather_px=4,
        left_overlap=True,
        right_overlap=True,
        top_overlap=True,
        bottom_overlap=True
    )
    # Edges should decrease to 0 at corners
    assert mask2[0, 0] == 0.0
    assert mask2[5, 5] == 1.0

def test_upscaler_stitching_and_progress():
    # Make a mock 100x100 solid image
    img = Image.new("RGB", (100, 100), color=(100, 150, 200))
    
    progress_updates = []
    def progress_cb(percent, msg):
        progress_updates.append((percent, msg))
        
    def custom_process_tile(tile: Image.Image, upscale_factor: float, **kwargs) -> Image.Image:
        w, h = tile.size
        new_w, new_h = int(w * upscale_factor), int(h * upscale_factor)
        tile_arr = np.array(tile)
        avg_color = tile_arr.mean(axis=(0, 1)).astype(np.uint8)
        return Image.new("RGB", (new_w, new_h), color=tuple(avg_color))
    
    upscaler = TileUpscaler(tile_size=40, overlap=0.25)
    
    # Upscale 2.0x
    result = upscaler.upscale(
        img,
        upscale_factor=2.0,
        process_tile_fn=custom_process_tile,
        progress_callback=progress_cb
    )
    
    # Assert dimensions
    assert result.size == (200, 200)
    
    # Assert progress callbacks executed
    assert len(progress_updates) > 0
    assert progress_updates[-1][0] == 100 # Ends at 100%
    
    # Assert color consistency
    res_arr = np.array(result)
    assert np.allclose(res_arr[10:190, 10:190, 0], 100, atol=2)
    assert np.allclose(res_arr[10:190, 10:190, 1], 150, atol=2)
    assert np.allclose(res_arr[10:190, 10:190, 2], 200, atol=2)
