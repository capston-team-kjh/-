import { Codex } from "@openai/codex-sdk";

function readStdin() {
  return new Promise((resolve, reject) => {
    let value = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      value += chunk;
    });
    process.stdin.on("end", () => resolve(value));
    process.stdin.on("error", reject);
  });
}

function requiredObject(value, name) {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${name} must be an object`);
  }
  return value;
}

async function main() {
  const request = requiredObject(JSON.parse(await readStdin()), "request");
  if (typeof request.prompt !== "string" || request.prompt.length === 0) {
    throw new Error("request.prompt must be a non-empty string");
  }
  if (!Array.isArray(request.image_paths) || request.image_paths.length === 0) {
    throw new Error("request.image_paths must contain at least one local image");
  }

  const options = {};
  if (process.env.CODEX_API_KEY) {
    options.apiKey = process.env.CODEX_API_KEY;
  }
  const codex = new Codex(options);
  const threadOptions = {
    workingDirectory: request.working_directory,
    sandboxMode: "read-only",
    approvalPolicy: "never",
    networkAccessEnabled: false,
  };
  if (request.model) {
    threadOptions.model = request.model;
  }
  if (request.model_reasoning_effort) {
    threadOptions.modelReasoningEffort = request.model_reasoning_effort;
  }

  const thread = request.thread_id
    ? codex.resumeThread(request.thread_id, threadOptions)
    : codex.startThread(threadOptions);
  const input = [
    { type: "text", text: request.prompt },
    ...request.image_paths.map((path) => ({ type: "local_image", path })),
  ];
  const turn = await thread.run(input, {
    outputSchema: requiredObject(request.output_schema, "request.output_schema"),
  });

  process.stdout.write(
    JSON.stringify({
      thread_id: thread.id,
      final_response: turn.finalResponse,
      usage: turn.usage,
    }),
  );
}

main().catch((error) => {
  const message = error instanceof Error ? error.stack || error.message : String(error);
  process.stderr.write(`${message}\n`);
  process.exitCode = 1;
});
