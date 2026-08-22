/**
 * Id and label minting shared by the editor store and anything that clones
 * elements into a net (paste, duplicate). Both need the same guarantee: the
 * result collides with nothing already in the target net.
 */

/** First free `${prefix}${n}` id, counting from the size of `existing`. */
export function nextId(prefix: string, existing: readonly { id: string }[]): string {
  let n = existing.length + 1;
  const taken = new Set(existing.map((e) => e.id));
  // eslint-disable-next-line no-constant-condition
  while (true) {
    const id = `${prefix}${n}`;
    if (!taken.has(id)) return id;
    n++;
  }
}

/**
 * `base` if it is free, otherwise `base_2`, `base_3`, … Pass `startNum` to
 * always number the label (Place_1, Place_2, …) rather than leaving the first
 * one bare.
 */
export function nextLabel(
  base: string,
  existing: readonly { name: string }[],
  startNum?: number,
): string {
  const taken = new Set(existing.map((e) => e.name));
  if (startNum === undefined) {
    if (!taken.has(base)) return base;
    let n = 2;
    while (taken.has(`${base}_${n}`)) n++;
    return `${base}_${n}`;
  }
  let n = startNum;
  while (taken.has(`${base}_${n}`)) n++;
  return `${base}_${n}`;
}
