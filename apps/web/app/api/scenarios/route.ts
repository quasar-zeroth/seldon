import { NextResponse } from "next/server";
import { scenariosApi } from "../../../src/lib/api";

export async function POST(request: Request) {
  try {
    const body = await request.json();
    const scenario = await scenariosApi.create({
      name: String(body.name || ""),
      target_question: String(body.target_question || ""),
      time_horizon: String(body.time_horizon || ""),
      description: String(body.description || ""),
      original_prompt: typeof body.original_prompt === "string" ? body.original_prompt : undefined,
    });
    return NextResponse.json(scenario, { status: 201 });
  } catch (error) {
    return NextResponse.json({ error: error instanceof Error ? error.message : "Scenario creation failed" }, { status: 502 });
  }
}
