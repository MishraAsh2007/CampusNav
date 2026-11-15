// This specific ILC topology was withdrawn after doorway/floor/corridor corrections.
// An older backend may still label it "reviewed"; that cannot restore eligibility.
export function isWithdrawnIndoorMap(model) {
  return model?.id === 'ilc' && model.nodes?.has('ilc-junction-f1');
}
