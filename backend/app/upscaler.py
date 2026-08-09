import logging
import time
import numpy as np
from PIL import Image
from typing import Callable, Optional, Tuple, List

logger = logging.getLogger(__name__)

def calculate_tile_size(width: int, height: int, available_vram_gb: float) -> int:
    """
    Calculate the optimal tile size based on the input image resolution and available VRAM.
    VRAM guide:
    - < 8GB: 512px
    - 8GB to 12GB: 768px
    - > 12GB: 1024px
    """
    if available_vram_gb < 8.0:
        base_size = 512
    elif available_vram_gb < 12.0:
        base_size = 768
    else:
        base_size = 1024
    
    # If the image is smaller than the calculated size, cap it at the image dimensions
    max_dim = max(width, height)
    if max_dim < base_size:
        # Round up index to multiple of 64 for Stable Diffusion compatibility
        return max(64, ((max_dim + 63) // 64) * 64)
    
    return base_size

def generate_feather_mask(
    width: int,
    height: int,
    feather_px: int,
    left_overlap: bool,
    right_overlap: bool,
    top_overlap: bool,
    bottom_overlap: bool
) -> np.ndarray:
    """
    Generates a 2D float weight mask of shape (height, width).
    Weights are 1.0 in the middle and decrease linearly to 0.0 near the edges that have overlaps.
    """
    mask = np.ones((height, width), dtype=np.float32)
    if feather_px <= 0:
        return mask
    
    x_ramp = np.arange(width, dtype=np.float32)
    x_weight = np.ones_like(x_ramp)
    if left_overlap:
        x_weight = np.minimum(x_weight, x_ramp / feather_px)
    if right_overlap:
        x_weight = np.minimum(x_weight, (width - 1 - x_ramp) / feather_px)
    x_weight = np.clip(x_weight, 0.0, 1.0)
    
    y_ramp = np.arange(height, dtype=np.float32)
    y_weight = np.ones_like(y_ramp)
    if top_overlap:
        y_weight = np.minimum(y_weight, y_ramp / feather_px)
    if bottom_overlap:
        y_weight = np.minimum(y_weight, (height - 1 - y_ramp) / feather_px)
    y_weight = np.clip(y_weight, 0.0, 1.0)
    
    return np.outer(y_weight, x_weight)

def default_mock_process_tile(tile: Image.Image, upscale_factor: float, **kwargs) -> Image.Image:
    """
    Fallback mock tile processing that resizes the tile using bilinear/bicubic scaling
    and adds a slight contrast/noise adjustment to simulate upscaled high-frequency detail.
    """
    w, h = tile.size
    new_w, new_h = int(w * upscale_factor), int(h * upscale_factor)
    upscaled = tile.resize((new_w, new_h), Image.Resampling.BICUBIC)
    
    # Add a mock high-frequency detail simulation (adds a tiny bit of grain or contrast)
    arr = np.array(upscaled, dtype=np.float32)
    # Give a tiny touch of high-pass enhancement to simulate Magnific upscaler detail
    noise = np.random.normal(0, 1.0, arr.shape).astype(np.float32)
    enhanced = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(enhanced)

class TileUpscaler:
    def __init__(
        self,
        tile_size: Optional[int] = None,
        overlap: float = 0.25,
        available_vram_gb: float = 16.0
    ):
        self.preset_tile_size = tile_size
        self.overlap_ratio = overlap
        self.available_vram_gb = available_vram_gb

    def upscale(
        self,
        image: Image.Image,
        upscale_factor: float = 2.0,
        process_tile_fn: Optional[Callable[[Image.Image, float], Image.Image]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        **kwargs
    ) -> Image.Image:
        """
        Splits high-res image into overlapping patches, processes each patch via process_tile_fn,
        and stitches them back using gradient alpha feather blending.
        """
        width, height = image.size
        
        # Calculate/retrieve optimal tile size
        if self.preset_tile_size is not None:
            tile_size = self.preset_tile_size
        else:
            tile_size = calculate_tile_size(width, height, self.available_vram_gb)
        
        overlap_px = int(tile_size * self.overlap_ratio)
        step_size = tile_size - overlap_px
        if step_size <= 0:
            step_size = tile_size // 2  # prevent infinite loop if overlap >= 1.0
        
        logger.info(f"Tiled Upscale Config: tile_size={tile_size}, overlap_px={overlap_px}, step_size={step_size}")
        
        # Determine tile boundaries
        tiles_coords = []  # List of tuples: (x_start, y_start, x_end, y_end)
        
        y = 0
        while y < height:
            y_end = min(y + tile_size, height)
            y_start = max(0, y_end - tile_size)
            
            x = 0
            while x < width:
                x_end = min(x + tile_size, width)
                x_start = max(0, x_end - tile_size)
                
                tiles_coords.append((x_start, y_start, x_end, y_end))
                
                if x_end >= width:
                    break
                x += step_size
            
            if y_end >= height:
                break
            y += step_size
        
        num_tiles = len(tiles_coords)
        logger.info(f"Splitting image into {num_tiles} overlapping tiles")
        
        # Stitched dimensions
        out_w = int(width * upscale_factor)
        out_h = int(height * upscale_factor)
        
        # Initialize output image accumulator and weight mask accumulator
        # We accumulate floats to avoid truncation and allow proper dividing
        output_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
        weight_acc = np.zeros((out_h, out_w), dtype=np.float32)
        
        tile_processor = process_tile_fn if process_tile_fn is not None else default_mock_process_tile
        
        # Process each tile
        for idx, (x_start, y_start, x_end, y_end) in enumerate(tiles_coords):
            tile_box = (x_start, y_start, x_end, y_end)
            tile_image = image.crop(tile_box)
            
            # Process tile (returns upscaled PIL Image)
            processed_tile = tile_processor(tile_image, upscale_factor, **kwargs)
            
            # Convert to numpy array of shapes (tile_height * S, tile_width * S, 3)
            tile_arr = np.array(processed_tile, dtype=np.float32)
            
            # Calculate output coordinates
            ox_start = int(x_start * upscale_factor)
            oy_start = int(y_start * upscale_factor)
            ox_end = ox_start + tile_arr.shape[1]
            oy_end = oy_start + tile_arr.shape[0]
            
            # Clip bounds to output size to avoid precision error issues at right/bottom edges
            oy_end = min(oy_end, out_h)
            ox_end = min(ox_end, out_w)
            
            tile_w = ox_end - ox_start
            tile_h = oy_end - oy_start
            
            # Trim the tile array if boundary rounding exceeded output canvas dimensions
            tile_arr = tile_arr[:tile_h, :tile_w, :3]
            
            # Determine overlap boundary directions
            left_overlap = (x_start > 0)
            right_overlap = (x_end < width)
            top_overlap = (y_start > 0)
            bottom_overlap = (y_end < height)
            
            # Generate 2D feathering mask for this tile
            feather_px = int(overlap_px * upscale_factor)
            mask = generate_feather_mask(
                width=tile_w,
                height=tile_h,
                feather_px=feather_px,
                left_overlap=left_overlap,
                right_overlap=right_overlap,
                top_overlap=top_overlap,
                bottom_overlap=bottom_overlap
            )
            
            # Accumulate weight and weighted colors
            output_acc[oy_start:oy_end, ox_start:ox_end, :] += tile_arr * mask[:, :, np.newaxis]
            weight_acc[oy_start:oy_end, ox_start:ox_end] += mask
            
            # Report progress
            if progress_callback is not None:
                percent = int(((idx + 1) / num_tiles) * 100)
                progress_callback(percent, f"Processed tile {idx + 1}/{num_tiles}")
        
        # Avoid division by zero: where weight is 0 (should not happen if tiles cover the whole canvas), set to 1
        num_zeros = np.sum(weight_acc == 0)
        if num_zeros > 0:
            logger.warning(f"Found {num_zeros} pixels in weight accumulator with value 0. Normalizing to fallback weight 1.")
            weight_acc[weight_acc == 0] = 1.0
            
        # Divide output accumulated images by weight mask to get average blended colors
        final_arr = output_acc / weight_acc[:, :, np.newaxis]
        final_arr = np.clip(final_arr, 0.0, 255.0).astype(np.uint8)
        
        return Image.fromarray(final_arr)
