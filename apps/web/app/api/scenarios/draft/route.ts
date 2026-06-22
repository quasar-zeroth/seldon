import { NextResponse } from "next/server";
import { scenariosApi } from "../../../../src/lib/api";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const prompt = typeof body.prompt === "string" ? body.prompt : "";
    const default_time_horizon = typeof body.default_time_horizon === "string" ? body.default_time_horizon : undefined;
    if (!prompt.trim()) return NextResponse.json({ error: "Prompt is required" }, { status: 422 });
    const draft = await scenariosApi.draft({ prompt, default_time_horizon });
    return NextResponse.json(draft);
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Scenario drafting failed" }, { status: 502 });
  }
}
