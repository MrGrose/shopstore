/** OR внутри группы, AND между группами. */
export type VariantConstraintGroup = {
  /** Debug only — resolver MUST NOT branch on id. */
  readonly id?: string;
  readonly tokens: readonly string[];
};

export type VariantConstraintPreset = readonly VariantConstraintGroup[];
