import { readFile, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import * as ort from "onnxruntime-web";

import {
  decodeOnnxPrediction,
  loadBrowserModel,
  type BrowserModelSessionContract,
  type BrowserModelValueMetadata,
} from "../src/ai/browser-model-loader";


export interface CandidateValidationOptions {
  metadataPath: string;
  modelPath?: string;
  reportPath?: string;
}

export interface CandidateCompatibilityReport {
  onnx_load: "pass";
  input_contract: "pass";
  output_contract: "pass";
  metadata: "pass";
  model_sha256: string;
  schema_version: string;
  model_version: string;
  input_names: readonly string[];
  output_names: readonly string[];
  feature_count: number;
  class_order: readonly string[];
  sample_prediction: string;
  sample_confidence: number;
}

type RunnableSession = BrowserModelSessionContract & {
  run(feeds: Record<string, ort.Tensor>): Promise<Record<string, ort.Tensor>>;
};

const normalizeValueMetadata = (
  name: string,
  raw: unknown,
): BrowserModelValueMetadata => {
  const value = raw && typeof raw === "object" ? raw as Record<string, unknown> : {};
  const shape = value.shape ?? value.dimensions ?? value.dims;
  const type = value.type ?? value.tensorType;
  return {
    name,
    isTensor: typeof value.isTensor === "boolean" ? value.isTensor : true,
    ...(typeof type === "string" ? { type } : {}),
    ...(Array.isArray(shape) ? { shape: shape as (number | string)[] } : {}),
  };
};

const metadataAt = (metadata: unknown, name: string, index: number): unknown => {
  if (Array.isArray(metadata)) return metadata[index];
  if (metadata && typeof metadata === "object") return (metadata as Record<string, unknown>)[name];
  return undefined;
};

const adaptSession = (session: ort.InferenceSession): RunnableSession => {
  const raw = session as unknown as Record<string, unknown>;
  const inputNames = [...session.inputNames];
  const outputNames = [...session.outputNames];
  return {
    inputNames,
    outputNames,
    inputMetadata: inputNames.map((name, index) =>
      normalizeValueMetadata(name, metadataAt(raw.inputMetadata, name, index))),
    outputMetadata: outputNames.map((name, index) =>
      normalizeValueMetadata(name, metadataAt(raw.outputMetadata, name, index))),
    run: (feeds) => session.run(feeds),
  };
};

const arrayBuffer = (bytes: Uint8Array): ArrayBuffer => Uint8Array.from(bytes).buffer;

export const validateCandidate = async (
  options: CandidateValidationOptions,
): Promise<CandidateCompatibilityReport> => {
  const metadataPath = resolve(options.metadataPath);
  const rawMetadata = JSON.parse(await readFile(metadataPath, "utf-8")) as Record<string, unknown>;
  const declaredModelPath = String(rawMetadata.model_path ?? "");
  const modelPath = resolve(options.modelPath ?? resolve(dirname(metadataPath), declaredModelPath));
  const modelBytes = new Uint8Array(await readFile(modelPath));
  let runtimeSession: RunnableSession | null = null;
  ort.env.wasm.numThreads = 1;

  const loaded = await loadBrowserModel(metadataPath, {
    fetchJson: async () => rawMetadata,
    fetchBinary: async () => arrayBuffer(modelBytes),
    createSession: async (bytes) => {
      const session = await ort.InferenceSession.create(bytes, { executionProviders: ["wasm"] });
      runtimeSession = adaptSession(session);
      return runtimeSession;
    },
  });
  if (runtimeSession === null) throw new Error("ONNX browser session was not created");

  const vector = new Float32Array(loaded.metadata.feature_names.length);
  const input = new ort.Tensor("float32", vector, [1, vector.length]);
  const output = await runtimeSession.run({ [runtimeSession.inputNames[0]]: input });
  const labelTensor = output[runtimeSession.outputNames[0]];
  const probabilityTensor = output[runtimeSession.outputNames[1]];
  if (!labelTensor || !probabilityTensor) throw new Error("ONNX browser session returned missing outputs");
  const decoded = decodeOnnxPrediction(
    loaded.metadata,
    labelTensor.data as ArrayLike<unknown>,
    probabilityTensor.data as ArrayLike<number>,
  );
  const classIndex = loaded.metadata.class_names.indexOf(decoded.rawState);
  const confidence = Number(probabilityTensor.data[classIndex]);
  const report: CandidateCompatibilityReport = {
    onnx_load: "pass",
    input_contract: "pass",
    output_contract: "pass",
    metadata: "pass",
    model_sha256: loaded.metadata.model_sha256,
    schema_version: loaded.metadata.schema_version,
    model_version: loaded.metadata.model_version,
    input_names: runtimeSession.inputNames,
    output_names: runtimeSession.outputNames,
    feature_count: loaded.metadata.feature_names.length,
    class_order: loaded.metadata.class_names,
    sample_prediction: decoded.rawState,
    sample_confidence: confidence,
  };
  if (options.reportPath) {
    await writeFile(resolve(options.reportPath), `${JSON.stringify(report, null, 2)}\n`, {
      encoding: "utf-8",
      flag: "wx",
    });
  }
  return report;
};

const cliOptions = (args: readonly string[]): CandidateValidationOptions => {
  const value = (name: string): string | undefined => {
    const index = args.indexOf(name);
    return index >= 0 ? args[index + 1] : undefined;
  };
  const metadataPath = value("--metadata");
  if (!metadataPath) throw new Error("usage: --metadata <path> [--onnx <path>] [--report <path>]");
  return {
    metadataPath,
    ...(value("--onnx") ? { modelPath: value("--onnx") } : {}),
    ...(value("--report") ? { reportPath: value("--report") } : {}),
  };
};

const invokedPath = process.argv[1] ? resolve(process.argv[1]) : "";
if (invokedPath && resolve(fileURLToPath(import.meta.url)) === invokedPath) {
  const report = await validateCandidate(cliOptions(process.argv.slice(2)));
  process.stdout.write(`${JSON.stringify(report, null, 2)}\n`);
}
