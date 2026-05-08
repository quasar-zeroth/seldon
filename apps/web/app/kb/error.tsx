"use client";
import { ErrorState } from "../../src/components/ui";
export default function Error({ error }: { error: Error }) { return <ErrorState message={error.message} />; }
