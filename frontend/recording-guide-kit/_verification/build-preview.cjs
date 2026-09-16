const fs = require("node:fs");
const path = require("node:path");
const dependencies = path.resolve(process.argv[2] || path.join(__dirname, "..", "..", "node_modules"));
const esbuild = require(path.join(dependencies, "esbuild"));
const root = path.resolve(__dirname, "..");

async function main() {
  const result = await esbuild.build({
    entryPoints: [path.join(__dirname, "preview.tsx")],
    bundle: true,
    write: false,
    outfile: path.join(__dirname, "preview.js"),
    nodePaths: [dependencies],
    jsx: "automatic",
    format: "iife",
    minify: true,
    target: ["es2020"],
    define: { "process.env.NODE_ENV": '"production"' },
    logLevel: "info",
  });
  const js = result.outputFiles.find((file) => file.path.endsWith(".js")).text;
  const css = result.outputFiles.find((file) => file.path.endsWith(".css")).text;
  const demoCss = `body{margin:0;background:#fafcfc;font-family:Arial,"Malgun Gothic",sans-serif;color:#22383e}.demo-toolbar{display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap;padding:14px 28px;border-bottom:1px solid #dce7e8;background:white}.demo-toolbar strong{font-size:17px}.demo-toolbar strong span{font-size:11px;color:#586d73;font-weight:400;margin-left:8px}.demo-toolbar>div{display:flex;gap:6px}.demo-toolbar button,.demo-controls button,.demo-back{font:inherit;font-size:12px;border:1px solid #dce7e8;border-radius:7px;background:white;color:#22383e;padding:9px 12px;cursor:pointer}.demo-toolbar button[aria-pressed=true]{background:#1a667a;color:white;border-color:#1a667a}.demo-checklist{max-width:850px;padding:28px 20px;margin:auto}.demo-caption{font-size:12px;color:#586d73;margin:0 0 16px}.demo-controls{display:flex;gap:14px;align-items:center;flex-wrap:wrap;background:#edf3f4;padding:15px;margin-top:20px;border-radius:10px;font-size:12px}.demo-controls label{display:flex;align-items:center;gap:5px}.demo-back{margin-top:20px}@media(max-width:420px){.demo-toolbar{padding:12px 16px}.demo-checklist{padding:20px 12px}}`;
  const html = `<!doctype html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FocusAI 촬영 가이드 미리보기</title><style>${demoCss}\n${css}</style></head><body><div id="root"></div><script>${js.replace(/<\/script/gi, "<\\/script")}</script></body></html>`;
  fs.writeFileSync(path.join(root, "preview.html"), html, "utf8");
  console.log(`PASS: React/TypeScript + CSS bundle (${result.warnings.length} warnings). Standalone preview.html created.`);
}

main().catch((error) => { console.error(error); process.exitCode = 1; });
