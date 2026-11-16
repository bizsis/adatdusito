import type { Request } from "../classification/category02Contract";
import {
  decodeOverview,
  decodeParameters,
  decodePreview,
  decodeApplied,
  decodeAlias,
  decodeAliases,
  decodeRun,
  decodeJob,
  type AliasInput,
  type RunScope,
  type SlotAction,
} from "./liveContract";
export function parameterApi(api: Request) {
  async function request<T>(
    url: string,
    decode: (v: unknown) => T,
    method = "GET",
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    return decode(await api<unknown>(url, method, body, signal));
  }
  const productPath = (product: string) =>
    `/workspace/products/${encodeURIComponent(product)}/parameters`;
  return {
    list: (query: URLSearchParams, signal: AbortSignal) =>
      request(
        `/workspace/parameter-diff?${query}`,
        decodeOverview,
        "GET",
        undefined,
        signal,
      ),
    read: (product: string, signal: AbortSignal) =>
      request(productPath(product), decodeParameters, "GET", undefined, signal),
    preview: (product: string, signal: AbortSignal) =>
      request(
        productPath(product) + "/preview",
        decodePreview,
        "POST",
        {},
        signal,
      ),
    apply: (product: string, revision: number, signal: AbortSignal) =>
      request(
        productPath(product) + "/apply",
        decodeApplied,
        "POST",
        { expected_revision: revision },
        signal,
      ),
    patch: (
      product: string,
      slot: string,
      body: SlotAction,
      signal: AbortSignal,
    ) =>
      request(
        productPath(product) + "/" + encodeURIComponent(slot),
        decodeParameters,
        "PATCH",
        body,
        signal,
      ),
    aliases: (query: URLSearchParams, signal: AbortSignal) =>
      request(
        `/workspace/parameter-aliases?${query}`,
        decodeAliases,
        "GET",
        undefined,
        signal,
      ),
    createAlias: (body: AliasInput, signal: AbortSignal) =>
      request(
        "/workspace/parameter-aliases",
        decodeAlias,
        "POST",
        body,
        signal,
      ),
    revokeAlias: (id: number, version: number, signal: AbortSignal) =>
      request(
        `/workspace/parameter-aliases/${id}?expected_version=${version}`,
        decodeAlias,
        "DELETE",
        undefined,
        signal,
      ),
    run: (
      mode: "preview" | "apply",
      scope: RunScope,
      after: number,
      signal: AbortSignal,
    ) =>
      request(
        "/workspace/parameter-runs",
        decodeRun,
        "POST",
        { mode, scope, start_after_product_id: after },
        signal,
      ),
    job: (id: number, signal: AbortSignal) =>
      request(
        `/workspace/product-jobs/${id}`,
        decodeJob,
        "GET",
        undefined,
        signal,
      ),
  };
}
export type LiveParameterApi = ReturnType<typeof parameterApi>;
