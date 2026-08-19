import { useEffect } from "react";

/**
 * Scroll-triggered reveal.
 *
 * Elements marked `data-reveal` start slightly lowered and transparent, then
 * settle as they enter the viewport. Staggering is expressed in the markup via
 * `data-reveal-delay` (in ms) so a row of cards resolves in sequence rather
 * than snapping in together.
 *
 * Deliberately one-way: once revealed, an element stays revealed. Re-hiding on
 * scroll-up reads as a glitch rather than an effect.
 *
 * Honours `prefers-reduced-motion` by revealing everything immediately, so the
 * page is never gated on an animation the reader asked not to see.
 */
export function useReveal() {
  useEffect(() => {
    const nodes = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    if (nodes.length === 0) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (reduced || typeof IntersectionObserver === "undefined") {
      nodes.forEach((n) => n.setAttribute("data-revealed", "true"));
      return;
    }

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;
          const el = entry.target as HTMLElement;
          const delay = Number(el.dataset.revealDelay ?? 0);
          window.setTimeout(() => el.setAttribute("data-revealed", "true"), delay);
          observer.unobserve(el);
        });
      },
      // Fire a little before the element's top edge reaches the fold, so the
      // motion has finished by the time it's properly in view.
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );

    nodes.forEach((n) => observer.observe(n));
    return () => observer.disconnect();
  }, []);
}
