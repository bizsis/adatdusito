import React, { useEffect, useRef, useState } from "react";
import { Expand, X } from "lucide-react";
import { helpHref, safeImage, type Block } from "./model";
type Picture = Extract<Block, { type: "image" }>;
function EnlargedImage({
  image,
  close,
}: {
  image: Picture;
  close: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = dialog.current;
    const previous = document.activeElement;
    node?.showModal();
    return () => {
      node?.close();
      if (previous instanceof HTMLElement && previous.isConnected)
        previous.focus();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="help-image-dialog"
      aria-label="Képernyőkép nagyítása"
      onCancel={close}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <button type="button" className="help-image-close" onClick={close}>
        <X size={18} aria-hidden="true" />
        Bezárás
      </button>
      <figure>
        <img src={image.src} alt={image.alt} />
        {image.caption && <figcaption>{image.caption}</figcaption>}
      </figure>
    </dialog>
  );
}
export function ArticleBody({ blocks }: { blocks: Block[] }) {
  const [image, setImage] = useState<Picture | null>(null);
  return (
    <>
      {blocks.map((block, i) => {
        switch (block.type) {
          case "heading":
            return <h3 key={i}>{block.text}</h3>;
          case "paragraph":
            return <p key={i}>{block.text}</p>;
          case "steps":
            return (
              <ol key={i}>
                {block.items.map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ol>
            );
          case "list":
            return (
              <ul key={i}>
                {block.items.map((item, j) => (
                  <li key={j}>{item}</li>
                ))}
              </ul>
            );
          case "note":
          case "warning":
            return (
              <aside
                key={i}
                className={`help-callout ${block.type}`}
                role="note"
              >
                <strong>{block.title}</strong>
                <p>{block.text}</p>
              </aside>
            );
          case "link":
            return (
              <p key={i}>
                <a href={helpHref(block.article)}>{block.text} →</a>
              </p>
            );
          case "image":
            return safeImage(block.src) ? (
              <figure key={i}>
                <button
                  type="button"
                  className="help-image-button"
                  aria-label={`Kép nagyítása: ${block.alt}`}
                  onClick={() => setImage(block)}
                >
                  <img
                    src={block.src}
                    alt={block.alt}
                    loading="lazy"
                    decoding="async"
                  />
                  <span>
                    <Expand size={16} aria-hidden="true" />
                    Nagyítás
                  </span>
                </button>
                {block.caption && <figcaption>{block.caption}</figcaption>}
              </figure>
            ) : null;
        }
      })}
      {image && <EnlargedImage image={image} close={() => setImage(null)} />}
    </>
  );
}
