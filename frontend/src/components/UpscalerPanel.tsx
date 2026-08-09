'use client';

import React, { useState, useEffect } from 'react';
import { X, Sliders, Save, Image as ImageIcon, Sparkles, Cpu, Loader2 } from 'lucide-react';
import { fetchSettings, saveSettings } from '../utils/api';

interface Preset {
  name: string;
  denoisingStrength: number;
  controlNetWeight: number;
}

const DEFAULT_PRESETS: Record<string, Preset> = {
  Portraits: { name: 'Portraits', denoisingStrength: 0.35, controlNetWeight: 1.25 },
  Anime: { name: 'Anime', denoisingStrength: 0.45, controlNetWeight: 1.10 },
  Landscapes: { name: 'Landscapes', denoisingStrength: 0.60, controlNetWeight: 0.85 },
  'Product Photography': { name: 'Product Photography', denoisingStrength: 0.25, controlNetWeight: 1.50 },
  '3D Renderings': { name: '3D Renderings', denoisingStrength: 0.40, controlNetWeight: 1.15 }
};

interface UpscalerPanelProps {
  filePath: string;
  onClose: () => void;
  onStartUpscale: (params: {
    denoising_strength: number;
    controlnet_weight: number;
    preset: string;
    preview: boolean;
  }) => Promise<void>;
}

export default function UpscalerPanel({ filePath, onClose, onStartUpscale }: UpscalerPanelProps) {
  const [preset, setPreset] = useState<string>('Portraits');
  const [denoisingStrength, setDenoisingStrength] = useState<number>(0.35);
  const [controlNetWeight, setControlNetWeight] = useState<number>(1.25);
  const [preview, setPreview] = useState<boolean>(false);
  const [customPresets, setCustomPresets] = useState<Record<string, Preset>>({});
  const [newPresetName, setNewPresetName] = useState<string>('');
  const [isSavingPreset, setIsSavingPreset] = useState<boolean>(false);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);

  // Load custom presets from base configurations
  useEffect(() => {
    async function loadPresets() {
      try {
        const configs = await fetchSettings();
        if (configs['upscaler:custom_presets']) {
          const parsed = JSON.parse(configs['upscaler:custom_presets']);
          setCustomPresets(parsed);
        }
      } catch (err) {
        console.error('Failed to load custom presets from configurations:', err);
      }
    }
    loadPresets();
  }, []);

  // Update sliders when preset changes
  useEffect(() => {
    if (preset === 'Custom') return;

    const selectedPreset = DEFAULT_PRESETS[preset] || customPresets[preset];
    if (selectedPreset) {
      setDenoisingStrength(selectedPreset.denoisingStrength);
      setControlNetWeight(selectedPreset.controlNetWeight);
    }
  }, [preset, customPresets]);

  // Handle slider changes (if changed manually, switch preset to Custom)
  const handleSliderChange = (type: 'denoising' | 'weight', val: number) => {
    if (type === 'denoising') {
      setDenoisingStrength(val);
    } else {
      setControlNetWeight(val);
    }
    
    // Check if values match any preset, if not, set to Custom
    let matched = false;
    const allPresets = { ...DEFAULT_PRESETS, ...customPresets };
    for (const [key, p] of Object.entries(allPresets)) {
      if (
        Math.abs(p.denoisingStrength - (type === 'denoising' ? val : denoisingStrength)) < 0.01 &&
        Math.abs(p.controlNetWeight - (type === 'weight' ? val : controlNetWeight)) < 0.01
      ) {
        setPreset(key);
        matched = true;
        break;
      }
    }
    if (!matched) {
      setPreset('Custom');
    }
  };

  const handleSavePreset = async () => {
    if (!newPresetName.trim()) return alert('Please enter a name for the custom preset');
    
    setIsSavingPreset(true);
    try {
      const updatedCustom = {
        ...customPresets,
        [newPresetName.trim()]: {
          name: newPresetName.trim(),
          denoisingStrength,
          controlNetWeight
        }
      };
      
      await saveSettings({
        'upscaler:custom_presets': JSON.stringify(updatedCustom)
      });
      
      setCustomPresets(updatedCustom);
      setPreset(newPresetName.trim());
      setNewPresetName('');
      alert('Custom preset saved successfully!');
    } catch (err: any) {
      alert(err.message || 'Failed to save custom preset');
    } finally {
      setIsSavingPreset(false);
    }
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    try {
      await onStartUpscale({
        denoising_strength: denoisingStrength,
        controlnet_weight: controlNetWeight,
        preset,
        preview
      });
    } catch (err: any) {
      alert(err.message || 'Upscaling request failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const allPresetKeys = [
    ...Object.keys(DEFAULT_PRESETS),
    ...Object.keys(customPresets),
    'Custom'
  ];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4">
      <div className="relative bg-slate-900 border border-slate-800 rounded-lg p-6 max-w-md w-full shadow-2xl animate-in fade-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="flex items-center justify-between pb-4 border-b border-slate-800">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-emerald-400" />
            <h3 className="text-base font-bold text-slate-200">Magnific Upscaler Settings</h3>
          </div>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-slate-400 p-1 rounded-md hover:bg-slate-800 transition"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Target Info */}
        <div className="mt-4 bg-slate-950/40 border border-slate-850 p-2 px-3 rounded flex items-center gap-2">
          <ImageIcon className="w-4 h-4 text-slate-500 flex-shrink-0" />
          <span className="text-xs text-slate-400 truncate font-mono">{filePath.split('/').pop()}</span>
        </div>

        {/* Form controls */}
        <div className="mt-4 space-y-4">
          {/* Preset drop down */}
          <div>
            <label className="block text-xs font-semibold text-slate-450 mb-1.5">Upscaling Preset</label>
            <select
              value={preset}
              onChange={(e) => setPreset(e.target.value)}
              className="w-full text-sm bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 focus:outline-none focus:border-emerald-500"
            >
              {allPresetKeys.map((key) => (
                <option key={key} value={key}>
                  {key}
                </option>
              ))}
            </select>
          </div>

          {/* Denoising Slider */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="text-xs font-semibold text-slate-450">Denoising Strength (Creativity)</label>
              <span className="text-xs font-mono font-bold text-emerald-400">{denoisingStrength.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0.1"
              max="1.0"
              step="0.05"
              value={denoisingStrength}
              onChange={(e) => handleSliderChange('denoising', parseFloat(e.target.value))}
              className="w-full accent-emerald-500 h-1.5 bg-slate-950 rounded-lg cursor-pointer"
            />
            <p className="text-[10px] text-slate-500 mt-1">Controls high-frequency texture generation and hallucination amount (0.1=low, 1.0=high)</p>
          </div>

          {/* ControlNet Weight Slider */}
          <div>
            <div className="flex justify-between items-center mb-1">
              <label className="text-xs font-semibold text-slate-450">ControlNet Weight (Resemblance)</label>
              <span className="text-xs font-mono font-bold text-emerald-400">{controlNetWeight.toFixed(2)}</span>
            </div>
            <input
              type="range"
              min="0.0"
              max="2.0"
              step="0.05"
              value={controlNetWeight}
              onChange={(e) => handleSliderChange('weight', parseFloat(e.target.value))}
              className="w-full accent-emerald-500 h-1.5 bg-slate-950 rounded-lg cursor-pointer"
            />
            <p className="text-[10px] text-slate-500 mt-1">Controls shape and structural adherence to the source image (0.0=none, 2.0=strict)</p>
          </div>

          {/* Render Mode check */}
          <div className="flex items-center justify-between p-2.5 bg-slate-950/20 border border-slate-850 rounded">
            <div>
              <span className="block text-xs font-semibold text-slate-350">Preview Mode (Small Region)</span>
              <span className="block text-[9px] text-slate-500">Upscales only a central 256x256 crop quickly before committing to a full render</span>
            </div>
            <input
              type="checkbox"
              checked={preview}
              onChange={(e) => setPreview(e.target.checked)}
              className="w-4 h-4 rounded text-emerald-500 focus:ring-emerald-500 focus:ring-offset-slate-900 focus:ring-2 bg-slate-900 border-slate-750"
            />
          </div>

          {/* Save custom preset form */}
          <div className="pt-3 border-t border-slate-850">
            <label className="block text-xs font-semibold text-slate-450 mb-1">Save Current as Custom Preset</label>
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="My Preset"
                value={newPresetName}
                onChange={(e) => setNewPresetName(e.target.value)}
                className="flex-1 text-xs bg-slate-950 border border-slate-800 rounded px-2 py-1 text-slate-300 focus:outline-none focus:border-emerald-500"
              />
              <button
                type="button"
                onClick={handleSavePreset}
                disabled={isSavingPreset}
                className="bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-[11px] font-semibold text-slate-300 px-3 py-1 rounded transition flex items-center gap-1 border border-slate-700"
              >
                {isSavingPreset ? <Loader2 className="w-3 h-3 animate-spin" /> : <Save className="w-3 h-3" />}
                Save
              </button>
            </div>
          </div>
        </div>

        {/* Footer actions */}
        <div className="mt-5 pt-4 border-t border-slate-800 flex justify-end gap-2.5">
          <button
            type="button"
            onClick={onClose}
            className="text-xs bg-transparent hover:bg-slate-850 border border-slate-800 hover:border-slate-700 text-slate-400 hover:text-slate-300 font-semibold px-4 py-2 rounded-md transition"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={isSubmitting}
            className="text-xs bg-emerald-600 hover:bg-emerald-500 disabled:bg-emerald-700 disabled:opacity-60 text-slate-100 font-bold px-4 py-2 rounded-md transition flex items-center gap-1.5 shadow-md shadow-emerald-950/20"
          >
            {isSubmitting ? (
              <>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                Initializing...
              </>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5" />
                Run Upscale
              </>
            )}
          </button>
        </div>

      </div>
    </div>
  );
}
