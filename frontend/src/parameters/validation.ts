import type { ParameterJob } from "./presentation";
export function validateParameterJob(job: ParameterJob) {
  if (
    !job ||
    ![
      "queued",
      "running",
      "paused",
      "partial",
      "completed",
      "failed",
      "cancelled",
      "superseded",
    ].includes(job.state) ||
    ![job.processed, job.changed, job.skipped, job.failed].every(
      (n) => Number.isSafeInteger(n) && n >= 0,
    ) ||
    (job.total !== null &&
      (!Number.isSafeInteger(job.total) || job.total < 0)) ||
    (job.progressPercent !== null &&
      (!Number.isFinite(job.progressPercent) ||
        job.progressPercent < 0 ||
        job.progressPercent > 100)) ||
    !Array.isArray(job.errors) ||
    job.errors.length > 100 ||
    !job.errors.every(
      (e) => e && typeof e.label === "string" && typeof e.message === "string",
    ) ||
    typeof job.key !== "string" ||
    typeof job.canResume !== "boolean" ||
    typeof job.canCancel !== "boolean" ||
    typeof job.message !== "string"
  )
    throw new Error("A futás állapotválasza nem értelmezhető.");
  return job;
}
