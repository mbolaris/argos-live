import { createHash } from 'node:crypto';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

const packageRoot = path.resolve(process.argv[2] ?? '');
if (!process.argv[2]) throw new Error('Usage: node patch-openclaw-liveness.mjs OPENCLAW_PACKAGE_ROOT');
const metadata = JSON.parse(await readFile(path.join(packageRoot, 'package.json'), 'utf8'));
if (metadata.name !== 'openclaw' || !/^2026\.10\./.test(metadata.version ?? ''))
  throw new Error('Unsupported OpenClaw package. Review the pinned source before extending this patch.');

const dist = path.join(packageRoot, 'dist');
const activityName = (await findOne(dist, /^diagnostic-run-activity-[A-Za-z0-9_-]+\.mjs$/));
const wrapperName = await findOne(dist, /^agent-tools\.before-tool-call-[A-Za-z0-9_-]+\.mjs$/);
const activityPath = path.join(dist, activityName);
const wrapperPath = path.join(dist, wrapperName);
let activity = await readFile(activityPath, 'utf8');
let wrapper = await readFile(wrapperPath, 'utf8');

const activityOld = 'return () => {\n\t\tif (resolveCurrentDiagnosticOwner(owner)) emitCoreSemanticRunProgressDiagnosticEvent({\n\t\t\trunId,\n\t\t\tsessionId: owner.sessionId,\n\t\t\tsessionKey: owner.sessionKey,\n\t\t\treason: `tool:${event.toolName}:completed`\n\t\t}, owner);\n\t};';
const activityNew = 'return (phase = "completed") => {\n\t\tif (resolveCurrentDiagnosticOwner(owner)) emitCoreSemanticRunProgressDiagnosticEvent({\n\t\t\trunId,\n\t\t\tsessionId: owner.sessionId,\n\t\t\tsessionKey: owner.sessionKey,\n\t\t\treason: `tool:${event.toolName}:${phase}`\n\t\t}, owner);\n\t};';
const wrapperOld = '\t\t\tconst recordProgress = captureDiagnosticToolProgress(eventBase);\n\t\t\trecordToolExecutionStarted(toolCallId, ctx?.runId);';
const wrapperNew = '\t\t\tconst recordProgress = captureDiagnosticToolProgress(eventBase);\n\t\t\tlet lastArgosProgressAt = 0;\n\t\t\tconst progressUpdate = normalizedToolName === "argos_evaluate" && typeof onUpdate === "function" ? (update) => {\n\t\t\t\tconst now = Date.now();\n\t\t\t\tif (!signal?.aborted && now - lastArgosProgressAt >= 30000) {\n\t\t\t\t\tlastArgosProgressAt = now;\n\t\t\t\t\trecordProgress?.("progress");\n\t\t\t\t}\n\t\t\t\treturn onUpdate(update);\n\t\t\t} : onUpdate;\n\t\t\trecordToolExecutionStarted(toolCallId, ctx?.runId);';
const argsOld = '\t\t\t\t\t\tonUpdate,\n\t\t\t\t\t\t...executionArgs';
const argsNew = '\t\t\t\t\t\tprogressUpdate,\n\t\t\t\t\t\t...executionArgs';

activity = replaceOnce(activity, activityOld, activityNew, activityPath);
wrapper = replaceOnce(wrapper, wrapperOld, wrapperNew, wrapperPath);
wrapper = replaceOnce(wrapper, argsOld, argsNew, wrapperPath);
await writeFile(activityPath, activity);
await writeFile(wrapperPath, wrapper);

const report = {
  schema: 'argos-openclaw-liveness-patch/1',
  upstream_version: metadata.version,
  behavior: 'argos_evaluate onUpdate refreshes owner-fenced semantic activity at most every 30 seconds; terminal completion remains separate',
  files: Object.fromEntries(await Promise.all([activityPath, wrapperPath].map(async (file) => [
    path.relative(packageRoot, file).replaceAll(path.sep, '/'),
    createHash('sha256').update(await readFile(file)).digest('hex'),
  ]))),
};
const reportPath = path.join(packageRoot, 'argos-liveness-patch.json');
await writeFile(reportPath, JSON.stringify(report, null, 2) + '\n', { flag: 'w' });
console.log(JSON.stringify(report));

async function findOne(directory, pattern) {
  const { readdir } = await import('node:fs/promises');
  const matches = (await readdir(directory)).filter((name) => pattern.test(name));
  if (matches.length !== 1) throw new Error(`Expected one pinned OpenClaw file matching ${pattern}, found ${matches.length}`);
  return matches[0];
}

function replaceOnce(source, before, after, file) {
  if (source.includes(after)) return source;
  const count = source.split(before).length - 1;
  if (count !== 1) throw new Error(`Expected one reviewed patch site in ${file}, found ${count}`);
  return source.replace(before, after);
}
