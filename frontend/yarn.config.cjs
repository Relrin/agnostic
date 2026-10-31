// Yarn constraints (`yarn constraints`): every dependency is pinned to an exact version, and a dependency used by
// several workspaces has the same version everywhere.
/** @type {import("@yarnpkg/types")} */
const EXACT = /^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$/;

module.exports = {
  async constraints({ Yarn }) {
    const byName = new Map();
    for (const dependency of Yarn.dependencies()) {
      if (dependency.range.startsWith("workspace:")) {
        if (dependency.range !== "workspace:*") dependency.update("workspace:*");
        continue;
      }
      if (!EXACT.test(dependency.range)) {
        dependency.error(
          `${dependency.ident} must be pinned to an exact version (got "${dependency.range}")`,
        );
      }
      if (dependency.type === "peerDependencies") continue;
      const first = byName.get(dependency.ident);
      if (first === undefined) byName.set(dependency.ident, dependency);
      else if (first.range !== dependency.range) dependency.update(first.range);
    }
  },
};
