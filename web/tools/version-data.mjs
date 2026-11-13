// Adapted from dtla-voxel (commit 3e77ad7, tools/version-data.mjs; see LICENSE-dtla-voxel).
// Build output only (dist/data; public/data is untouched): every data file but meta.json gets a copy named by its
// content hash under data/immutable/, and meta.json an `assets` map from path to hash. The viewer fetches the hashed
// copy and may keep it for good (util.ts), so a deploy that leaves a tile unchanged leaves it in the visitor's cache.
// The plain paths stay too, for tabs opened before a deploy.
import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

export function versionData(directory) {
  const metaFile = path.join(directory, 'meta.json');
  const meta = JSON.parse(fs.readFileSync(metaFile, 'utf8'));
  const assets = {}, immutable = path.join(directory, 'immutable');
  fs.mkdirSync(immutable, { recursive: true });
  const visit = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      const file = path.join(dir, entry.name);
      if (file === immutable || file === metaFile) continue;
      if (entry.isDirectory()) { visit(file); continue; }
      if (!entry.isFile()) continue;
      const bytes = fs.readFileSync(file);
      const hash = crypto.createHash('sha256').update(bytes).digest('hex').slice(0, 32);
      const target = path.join(immutable, `${hash}${path.extname(entry.name)}`);
      if (!fs.existsSync(target)) fs.writeFileSync(target, bytes);
      else if (!fs.readFileSync(target).equals(bytes)) throw new Error(`content-hash collision: ${file}`);
      assets[path.relative(directory, file).split(path.sep).join('/')] = `${hash}${path.extname(entry.name)}`;
    }
  };
  visit(directory);
  fs.writeFileSync(metaFile, JSON.stringify({ ...meta, assets }));
  return assets;
}

// the Vite plugin: runs after the build has copied public/ into dist/
export function versionedData() {
  let output;
  return {
    name: 'versioned-data',
    apply: 'build',
    configResolved(config) { output = path.resolve(config.root, config.build.outDir, 'data'); },
    closeBundle() { versionData(output); },
  };
}
