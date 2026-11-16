import React, { useCallback, useMemo, useState } from "react";
import type { Request } from "../classification/category02Contract";
import { usePresentationRead } from "../classification/usePresentationRead";
import { bulkApi } from "./bulkApi";
import { ApiHttpError } from "../apiResponse";
export function PreparationStatus({
  request,
  product,
}: {
  request: Request;
  product: string;
}) {
  const api = useMemo(() => bulkApi(request), [request]);
  const [tick, T] = useState(0);
  const load = useCallback(
    async (s: AbortSignal) => {
      void tick;
      try {
        return await api.productPreparation(product, s);
      } catch (e) {
        if (e instanceof ApiHttpError && e.status === 404) return null;
        throw e;
      }
    },
    [api, product, tick],
  );
  const read = usePresentationRead(load);
  const a = read.data?.approval;
  return (
    <section aria-label="Termék előkészítési jóváhagyása">
      <p>
        A tárolt paraméterhelyek és az előkészítési jóváhagyás külön állapotok.
      </p>
      {read.error && <p role="alert">{read.error}</p>}
      {read.data &&
        (a ? (
          <p>
            Jóváhagyás #{a.id} · {a.valid ? "Érvényes" : "Érvénytelen"} ·
            Rögzített termékrevízió: {a.product_revision}; aktuális:{" "}
            {read.data.revision}. Kutatandó hiány: {a.research_targets}.{" "}
            {a.invalid_reason || ""}
          </p>
        ) : (
          <p>Nincs aktív előkészítési jóváhagyás.</p>
        ))}
      <button onClick={() => T((v) => v + 1)}>
        Termék jóváhagyásának frissítése
      </button>
    </section>
  );
}
