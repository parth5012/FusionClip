import { create } from 'zustand';
import { canonicalRecipe, DEFAULT_RECIPE, type AdjustOpKey, type EditorRecipe } from '../utils/editor';

/** Full session history depth (#119: undo full session history ~50 snapshots). */
export const MAX_UNDO_SNAPSHOTS = 50;

export type RecipeParamKey = AdjustOpKey | 'rotate' | 'cropAspect';

interface EditorStoreState {
  /** Live recipe driving the preview canvas + Adjust panel. */
  recipe: EditorRecipe;
  /** Undo stack (oldest first, capped at MAX_UNDO_SNAPSHOTS). */
  past: EditorRecipe[];
  /** Redo stack (next redo last). Cleared by any new edit. */
  future: EditorRecipe[];
  /** Replace the recipe wholesale (asset load / version reload): resets history. */
  load: (recipe: EditorRecipe) => void;
  /** Set one param, pushing the pre-edit recipe for undo (no-op sets push nothing). */
  setParam: (key: RecipeParamKey, value: number | string) => void;
  /** Replace the whole recipe as one undoable edit (e.g. Cancel→reset uses reset instead). */
  setRecipe: (recipe: EditorRecipe) => void;
  undo: () => void;
  redo: () => void;
  /** Back to defaults with empty history. */
  reset: () => void;
  canUndo: () => boolean;
  canRedo: () => boolean;
}

function pushPast(past: EditorRecipe[], snapshot: EditorRecipe): EditorRecipe[] {
  const next = [...past, snapshot];
  return next.length > MAX_UNDO_SNAPSHOTS
    ? next.slice(next.length - MAX_UNDO_SNAPSHOTS)
    : next;
}

function withEdit(
  state: { recipe: EditorRecipe; past: EditorRecipe[] },
  next: EditorRecipe,
): { recipe: EditorRecipe; past: EditorRecipe[]; future: never[] } {
  return {
    recipe: next,
    past: pushPast(state.past, state.recipe),
    future: [],
  };
}

export const useEditorStore = create<EditorStoreState>()((set, get) => ({
  recipe: { ...DEFAULT_RECIPE },
  past: [],
  future: [],

  load: (recipe) => set({ recipe: { ...recipe }, past: [], future: [] }),

  setParam: (key, value) =>
    set((state) => {
      if (state.recipe[key] === value) return state; // no-op: no snapshot
      return withEdit(state, { ...state.recipe, [key]: value });
    }),

  setRecipe: (recipe) =>
    set((state) => {
      const next = { ...recipe };
      if (canonicalRecipe(next) === canonicalRecipe(state.recipe)) return state;
      return withEdit(state, next);
    }),

  undo: () =>
    set((state) => {
      if (state.past.length === 0) return state;
      const previous = state.past[state.past.length - 1];
      return {
        recipe: previous,
        past: state.past.slice(0, -1),
        future: [...state.future, state.recipe],
      };
    }),

  redo: () =>
    set((state) => {
      if (state.future.length === 0) return state;
      const next = state.future[state.future.length - 1];
      return {
        recipe: next,
        past: pushPast(state.past, state.recipe),
        future: state.future.slice(0, -1),
      };
    }),

  reset: () => set({ recipe: { ...DEFAULT_RECIPE }, past: [], future: [] }),

  canUndo: () => get().past.length > 0,
  canRedo: () => get().future.length > 0,
}));
