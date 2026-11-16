import React, { useEffect, useRef, useState } from "react";
import { BookOpen, Search, ArrowLeft } from "lucide-react";
import { ArticleBody } from "./ArticleBody";
import {
  helpHref,
  readHelpRoute,
  searchArticles,
  type Article,
  type Topic,
} from "./model";
import topics from "./topics.json";
import "./support.css";
const articles = Object.values(
  import.meta.glob<Article>("./articles/*.json", {
    eager: true,
    import: "default",
  }),
);
const orderedTopics: Topic[] = [...topics].sort((a, b) => a.order - b.order);
export default function HelpPage() {
  const [route, setRoute] = useState(() => readHelpRoute(window.location.hash));
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const changed = () => setRoute(readHelpRoute(window.location.hash));
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    if (route.article) heading.current?.focus();
  }, [route.article]);
  const article = articles.find((a) => a.id === route.article);
  const topic = orderedTopics.find(
    (t) => t.id === (article?.topic || route.topic),
  );
  const found = searchArticles(articles, route.query, route.topic);
  const home = helpHref(null, route.query, route.topic);
  const changeSearch = (query: string) => {
    const next = { ...route, query };
    window.history.replaceState(null, "", helpHref(null, query, route.topic));
    setRoute(next);
  };
  return (
    <div className="help-page">
      <p className="help-intro">
        Útmutatók az Adatdúsító használatához. A látható műveletek a
        munkaterületedtől és a jogosultságaidtól függnek.
      </p>
      {route.article ? (
        article ? (
          <>
            <nav aria-label="Segédlet útvonala" className="help-breadcrumb">
              <a href={home}>Segédlet</a>
              <span aria-hidden="true">/</span>
              <a href={helpHref(null, "", article.topic)}>{topic?.title}</a>
            </nav>
            <article className="card padded help-article" key={article.id}>
              <h2 ref={heading} tabIndex={-1}>
                {article.title}
              </h2>
              <p className="help-summary">{article.summary}</p>
              <ArticleBody blocks={article.blocks} />
              {!!article.related.length && (
                <nav aria-label="Kapcsolódó útmutatók" className="help-related">
                  <h3>Kapcsolódó útmutatók</h3>
                  {article.related.map((id) => {
                    const item = articles.find((a) => a.id === id);
                    return item ? (
                      <a key={id} href={helpHref(id, route.query, route.topic)}>
                        {item.title} →
                      </a>
                    ) : null;
                  })}
                </nav>
              )}
            </article>
            <a className="help-back" href={home}>
              <ArrowLeft size={16} aria-hidden="true" />
              Vissza a témakörökhöz
            </a>
          </>
        ) : (
          <section className="card padded" role="status">
            <h2 ref={heading} tabIndex={-1}>
              A cikk nem található
            </h2>
            <p>
              Lehet, hogy a hivatkozás hibás vagy az útmutató már más címen
              érhető el.
            </p>
            <a href={helpHref()}>Vissza a témakörökhöz</a>
          </section>
        )
      ) : (
        <>
          <section
            className="card padded help-search"
            aria-label="Keresés a segédletben"
          >
            <label htmlFor="help-search">
              <Search size={18} aria-hidden="true" />
              Keresés a segédletben
            </label>
            <input
              id="help-search"
              type="search"
              maxLength={256}
              value={route.query}
              onChange={(e) => changeSearch(e.target.value)}
              placeholder="Például: oszlopok, donorprofil, zárolás"
            />
            <p className="small muted">
              Címben és a teljes szövegben kereshetsz, ékezetek nélkül is.
            </p>
            <label className="help-topic-mobile" htmlFor="help-topic">
              Témakör
              <select
                id="help-topic"
                value={route.topic}
                onChange={(e) => {
                  window.location.hash = helpHref(
                    null,
                    route.query,
                    e.target.value,
                  );
                }}
              >
                <option value="">Összes témakör</option>
                {orderedTopics.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </select>
            </label>
            <p role="status" aria-live="polite">
              {found.length} útmutató
              {route.query ? ` a(z) „${route.query}” keresésre` : ""}
              {topic ? ` · ${topic.title}` : ""}
            </p>
          </section>
          <div className="help-layout">
            <nav
              className="card padded help-topics"
              aria-label="Segédlet témakörök"
            >
              <h2>Témakörök</h2>
              <a
                href={helpHref(null, route.query)}
                aria-current={!route.topic ? "page" : undefined}
              >
                Összes témakör
              </a>
              {orderedTopics.map((t) => (
                <a
                  key={t.id}
                  href={helpHref(null, route.query, t.id)}
                  aria-current={route.topic === t.id ? "page" : undefined}
                >
                  {t.title}
                </a>
              ))}
            </nav>
            <section aria-label="Útmutatók" className="help-results">
              {!found.length ? (
                <div className="card padded">
                  <h2>Nincs találat</h2>
                  <p>
                    Próbálj rövidebb kifejezést, vagy keress az összes
                    témakörben.
                  </p>
                  <a href={helpHref()}>Keresés és témakörszűrés törlése</a>
                </div>
              ) : (
                orderedTopics
                  .filter((t) => found.some((a) => a.topic === t.id))
                  .map((t) => (
                    <section className="card padded" key={t.id}>
                      <h2>{t.title}</h2>
                      <p className="muted">{t.description}</p>
                      <ul className="help-article-list">
                        {found
                          .filter((a) => a.topic === t.id)
                          .map((a) => (
                            <li key={a.id}>
                              <a
                                href={helpHref(a.id, route.query, route.topic)}
                              >
                                <BookOpen size={18} aria-hidden="true" />
                                <span>
                                  <strong>{a.title}</strong>
                                  <span>{a.summary}</span>
                                </span>
                              </a>
                            </li>
                          ))}
                      </ul>
                    </section>
                  ))
              )}
            </section>
          </div>
        </>
      )}
    </div>
  );
}
