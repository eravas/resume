// Traditional one-page résumé, laid out like the Word version.
// Reads the resolver's output; all selection, ordering and date
// formatting already happened there.
//
//   typst compile --root . \
//     --input data=/dist/resolved-pdf.json templates/resume.typ dist/resume.pdf

#let data = json(sys.inputs.at("data", default: "/dist/resolved-pdf.json"))
#let basics = data.basics
#let S = data.sections

// ---- style knobs ---------------------------------------------------------
#let accent = rgb("#1F3A5F")      // name, section headings
#let title-ink = rgb("#1E2A3A")   // entry titles
#let body-ink = rgb("#2B2B2B")
#let muted = rgb("#555555")
#let rule-ink = rgb("#A9B8C9")
// Same face as the Word version. Trebuchet MS can't be committed to a public
// repo; it's installed on the machine (Microsoft core fonts package) instead.
#let body-font = ("Trebuchet MS", "DejaVu Sans")
#let sep = " | "

#set document(title: basics.name + " — Résumé", author: basics.name)
#set page(paper: "us-letter", margin: (x: 0.68in, top: 0.5in, bottom: 0.5in))
#set text(font: body-font, size: 10pt, fill: body-ink, lang: "en")
#set par(leading: 0.42em, spacing: 0.42em, justify: false)

// ---- helpers ---------------------------------------------------------------

// The YAML's inline subset: **bold**, *italic*, [label](url). Text is never
// evaluated as Typst markup, so #, $, @, _ etc. in bullets are safe.
#let inline-re = regex("\\*\\*(.+?)\\*\\*|\\[([^\\]]+)\\]\\(([^)\\s]+)\\)|\\*(.+?)\\*")
#let inline(s) = {
  let out = ()
  let pos = 0
  for m in s.matches(inline-re) {
    out.push(s.slice(pos, m.start))
    let c = m.captures
    if c.at(0) != none {
      out.push(strong(c.at(0)))
    } else if c.at(1) != none {
      out.push(link(c.at(2), c.at(1)))
    } else {
      out.push(emph(c.at(3)))
    }
    pos = m.end
  }
  out.push(s.slice(pos))
  out.join()
}

#let contact-link(c) = {
  let url = c.at("url", default: none)
  if url == none and c.kind == "email" { url = "mailto:" + c.value }
  if url == none and c.kind == "phone" { url = "tel:" + c.value.replace("-", "").replace(" ", "") }
  if url == none { c.value } else { link(url, c.value) }
}

#let section(title) = block(above: 13pt, below: 7pt, sticky: true, stack(
  dir: ttb,
  spacing: 4pt,
  text(size: 11.5pt, weight: "bold", fill: accent, upper(title)),
  line(length: 100%, stroke: 0.6pt + rule-ink),
))

#let entry(title, sub: none, lines: (), bullets: ()) = block(above: 8pt, below: 0pt, breakable: false)[
  #text(size: 10.5pt, weight: "bold", fill: title-ink, title)
  #if sub != none [ \ #sub]
  #for l in lines [ \ #l]
  #if bullets.len() > 0 {
    block(above: 3pt, list(
      marker: [•],
      indent: 2pt,
      body-indent: 7pt,
      spacing: 3pt,
      ..bullets.map(h => inline(h.text)),
    ))
  }
]

#let joined(parts) = parts.filter(p => p != none and p != "").join(sep)
#let titled(name, place) = if place == none or place == "" { name } else { name + " - " + place }

// ---- header ------------------------------------------------------------------

#text(size: 28pt, weight: "bold", fill: accent, tracking: 0.05em, upper(basics.name))

#{
  let primary = basics.contact.filter(c => c.kind in ("phone", "email"))
  let rest = basics.contact.filter(c => not (c.kind in ("phone", "email")))
  set text(size: 9pt, fill: muted)
  block(above: 8pt, below: 0pt)[
    #primary.map(contact-link).join(sep)
    #if rest.len() > 0 [ \ #rest.map(contact-link).join(sep)]
  ]
}

// ---- sections, in the profile's order ---------------------------------------------

#let has-skills = "skills" in S and S.skills.len() > 0
#let has-certs = "certifications" in S and S.certifications.len() > 0

#let cert-text(k) = k.name + " (Earned: " + k.date_display + ")"
#let skill-name(i) = if type(i) == str { i } else { i.name }

#for (name, items) in S {
  if items.len() == 0 { continue }

  if name == "education" {
    section("Education")
    for e in items {
      let degree = e.degree + (if e.at("field", default: none) != none { ", " + e.field } else { "" })
      entry(
        titled(e.institution, e.at("location", default: none)),
        sub: joined((degree, e.at("dates", default: none))),
        lines: e.at("honors", default: ()).map(h => inline(h.text)),
        bullets: e.at("highlights", default: ()),
      )
    }
  } else if name == "skills" {
    section(if has-certs { "Technical Skills & Certifications" } else { "Technical Skills" })
    block(above: 8pt, {
      for g in items [
        *#g.label:* #g.at("items").map(skill-name).join(", ") \
      ]
      if has-certs [
        *Certifications:* #S.certifications.map(cert-text).join("; ")
      ]
    })
  } else if name == "certifications" {
    // Folded into the skills section when that exists.
    if not has-skills {
      section("Certifications")
      block(above: 8pt, S.certifications.map(cert-text).join(linebreak()))
    }
  } else if name == "projects" {
    section("Engineering Projects")
    for p in items {
      let bullets = p.at("highlights", default: ())
      entry(
        p.name,
        sub: joined((p.at("role", default: none), p.at("dates", default: none))),
        lines: if bullets.len() == 0 and p.at("summary", default: none) != none { (inline(p.summary),) } else { () },
        bullets: bullets,
      )
    }
  } else if name == "experience" {
    section("Experience")
    for x in items {
      entry(
        titled(x.organization, x.at("location", default: none)),
        sub: joined((x.title, x.at("dates", default: none))),
        bullets: x.at("highlights", default: ()),
      )
    }
  }
}

// ---- guard: a résumé is one page ----------------------------------------------
#context {
  let pages = counter(page).final().first()
  if pages > 1 {
    panic("résumé runs to " + str(pages) + " pages; trim the profile or the content")
  }
}
