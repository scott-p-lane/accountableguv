import fs from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

const runtimeRequire = createRequire('C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1105-1297-0_26.1105.1297.0_x64__3k8sg7r9htsxt/dependencies/node/package.json');
const { Workbook } = await import(pathToFileURL(runtimeRequire.resolve('@oai/artifact-tool')).href);
const root = path.dirname(fileURLToPath(import.meta.url));
const datasets = JSON.parse(await fs.readFile(path.join(root, 'source/datasets.json'), 'utf8'));
const outDir = path.join(root, 'data');
await fs.mkdir(outDir, { recursive: true });
const escapeCsv = value => {
  const text = value == null ? '' : String(value);
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};
const selected = process.argv[2];
if (selected && !Object.hasOwn(datasets, selected)) throw new Error(`Unknown dataset: ${selected}`);
for (const [name, records] of Object.entries(datasets)) {
  if (selected && name !== selected) continue;
  const wb = Workbook.create();
  const sheet = wb.worksheets.add('Data');
  const headers = Object.keys(records[0]);
  const values = [headers, ...records.map(row => headers.map(key => row[key]))];
  sheet.getRangeByIndexes(0, 0, values.length, headers.length).values = values;
  sheet.getRangeByIndexes(0, 0, 1, headers.length).format.font.bold = true;
  wb.recalculate();
  const inspected = await wb.inspect({ kind: 'table', range: 'Data!A1:F3', include: 'values', tableMaxRows: 3, tableMaxCols: 6, maxChars: 1000 });
  console.log(name, inspected.ndjson);
  // CSV has no formatting, formulas, charts, or rendering surface. Serialize
  // the authored cell matrix using RFC 4180 quoting, with CRLF record endings.
  const saved = sheet.getRangeByIndexes(0, 0, values.length, headers.length).values;
  if (JSON.stringify(saved) !== JSON.stringify(values)) throw new Error(`Cell round-trip mismatch: ${name}`);
  await fs.writeFile(path.join(outDir, name), saved.map(row => row.map(escapeCsv).join(',')).join('\r\n') + '\r\n', 'utf8');
  console.log(`Saved ${name}: ${records.length} records, ${headers.length} columns`);
}
