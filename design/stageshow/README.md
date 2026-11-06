# PolicyLens product preview

Not used at runtime. `node_modules/` and `dist/` are not kept; run `npm install` first.

This is the editable Stageshow source for the still used on the PolicyLens homepage. It uses the kit and film scripts copied from `benjitaylor/skills/stageshow` (see LICENSE and NOTICE.md). The Django page serves the exported PNGs and does not load React at runtime.

Node.js 20.19+ and Chrome are required to rebuild and inspect the still. On this Mac, Node 22 is installed through Homebrew:

```sh
npm install
npm run typecheck
npm run dev -- --port 5173
```

In a second terminal from this folder:

```sh
export CHROME_PATH="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
node scripts/film.mjs 'http://127.0.0.1:5173/' --select '.pl-stage' --still --out shots/policy-wide.png --gate
node scripts/film.mjs 'http://127.0.0.1:5173/' --select '.pl-stage' --width 390 --still --out shots/policy-mobile.png --gate
cp shots/policy-wide.png ../../server/static/policy-preview-wide.png
cp shots/policy-mobile.png ../../server/static/policy-preview-mobile.png
```

The `?gold` route shows the copied `static-card` reference for visual comparison. Do not treat that reference as PolicyLens product UI.
