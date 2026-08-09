import { readFile, writeFile } from "node:fs/promises";

const installerPath = new URL("../src/install.sh", import.meta.url);
const generatedModulePath = new URL("../src/install.generated.js", import.meta.url);
const installer = await readFile(installerPath);
const generatedModule = `export default ${JSON.stringify(installer.toString("base64"))};\n`;

await writeFile(generatedModulePath, generatedModule, { mode: 0o600 });
