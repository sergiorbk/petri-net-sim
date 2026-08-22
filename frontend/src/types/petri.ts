export type ArcType = "NORMAL" | "INHIBITOR" | "READ";
export type DistributionType = "exp" | "norm" | "unif" | "det";

export interface PetriPlace {
  id: string;
  name: string;
  tokens: number;
  graphics: { x: number; y: number };
  /** Owning object frame's id, or undefined for a free (unframed) place. */
  objectId?: string;
}

export interface PetriTransition {
  id: string;
  name: string;
  priority: number;
  distribution: DistributionType | null;
  mean_delay: number;
  standard_deviation: number;
  probability: number | null;
  graphics: { x: number; y: number };
  /** Owning object frame's id, or undefined for a free (unframed) transition. */
  objectId?: string;
}

export interface PetriArc {
  id: string;
  source_id: string;
  target_id: string;
  weight: number;
  arc_type: ArcType;
}

/**
 * A named, visible boundary grouping a subset of places/transitions into one
 * Petri-object ("composed model" feature) — matches PetriObjModelPaint's own
 * concept (docs/petri-object-models.md). Deliberately not named "Petri
 * object" in code: that name already belongs to this app's unrelated
 * flatten-on-drop template catalog (see petri-object-instantiate.ts).
 */
export interface ObjectFrame {
  id: string;
  name: string;
  priority: number;
  graphics: { x: number; y: number; width: number; height: number };
  collapsed?: boolean;
  /**
   * Enclosing frame, when this object was built inside another one. Absent =
   * the object sits directly on the net. The depth of this chain is the
   * object's abstraction level: the net is 0, objects on it are 1, objects
   * inside those are 2, and so on.
   */
  objectId?: string;
  /**
   * Absent/true = the frame keeps a fixed padding around its outermost
   * members and re-fits whenever they move. Set to false the moment the user
   * resizes the frame by hand, so a deliberate size is never overridden.
   */
  autoFit?: boolean;
  /**
   * Id of the petri-objects library entry this frame was instantiated from or
   * last saved to (see petri-objects-client). Null/absent = canvas-local only.
   */
  templateId?: string | null;
}

export type ObjectLinkType = "placeFusion" | "transitionToPlace" | "placeToTransition";

/**
 * A connection between two different objects — a shared place (placeFusion)
 * or a cross-object arc (transitionToPlace / placeToTransition). Never a
 * PetriArc: the wire format (and the Java model) treats this as a net-level
 * declaration, not a page-level arc.
 */
export interface ObjectLink {
  id: string;
  type: ObjectLinkType;
  /** Place id (fusion, placeToTransition) or transition id (transitionToPlace). */
  sourceId: string;
  /** Place id (fusion, transitionToPlace) or transition id (placeToTransition). */
  targetId: string;
  quantity: number;
  /** placeToTransition only: test the marking without consuming it. */
  informational?: boolean;
}

export interface PetriNetData {
  name: string;
  places: PetriPlace[];
  transitions: PetriTransition[];
  arcs: PetriArc[];
  /** Absent/empty = today's flat net, unchanged behavior everywhere. */
  objects?: ObjectFrame[];
  links?: ObjectLink[];
}

export type FiringPhase = "before_act_in" | "after_act_in" | "before_act_out" | "after_act_out";

export interface FiringStep {
  transition_id: string;
  phase: FiringPhase;
  markings: Record<string, number>;
  buffers: Record<string, number>;
}

export interface SimulationSnapshot {
  current_time: number;
  step_number: number;
  markings: Record<string, number>;
  buffers: Record<string, number>;
  progress: number;
  /** Transition IDs that fired (input or output) since the previous snapshot. */
  fired_transitions?: string[];
  /** Ordered sub-steps within this snapshot for detailed animation. */
  firing_sequence?: FiringStep[];
  /** Set on expanded sub-snapshots: which transition is active in this atomic step. */
  active_transition_id?: string;
  /** Set on expanded sub-snapshots: exact animation phase (mirrors Swing UI hooks). */
  active_phase?: FiringPhase;
}

export interface PlaceStats {
  id: string;
  name: string;
  final_marking: number;
  mean_marking: number;
  observed_min: number;
  observed_max: number;
}

export interface TransitionStats {
  id: string;
  name: string;
  final_buffer: number;
  mean_buffer: number;
  observed_min: number;
  observed_max: number;
}

export interface SimulationResult {
  simulation_time: number;
  final_time: number;
  total_steps: number;
  places: PlaceStats[];
  transitions: TransitionStats[];
}
