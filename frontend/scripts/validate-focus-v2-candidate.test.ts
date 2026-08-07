import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { expect, it } from "vitest";

import { FRONT_V2_SCHEMA } from "../src/ai/feature-schema";
import { validateCandidate } from "./validate-focus-v2-candidate";


it("rejects candidate bytes whose SHA-256 does not match metadata", async () => {
  const directory = await mkdtemp(join(tmpdir(), "focusai-v2-validator-"));
  const modelPath = join(directory, "candidate.onnx");
  const metadataPath = join(directory, "metadata.json");
  await writeFile(modelPath, new Uint8Array([1, 2, 3, 4]));
  await writeFile(
    metadataPath,
    JSON.stringify({
      model_version: "focus-state-v2-test",
      schema_version: FRONT_V2_SCHEMA.schema_version,
      feature_names: FRONT_V2_SCHEMA.feature_names,
      class_names: FRONT_V2_SCHEMA.class_names,
      normalization: FRONT_V2_SCHEMA.normalization,
      confidence_threshold: 0.65,
      camera_role: "front",
      model_path: "candidate.onnx",
      model_sha256: "0".repeat(64),
    }),
  );

  await expect(validateCandidate({ metadataPath, modelPath })).rejects.toThrow(/SHA-256 mismatch/);
});
