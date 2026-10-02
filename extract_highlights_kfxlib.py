#!/usr/bin/env python3
"""Extract highlight text from a KFX file using position data from a .yjr JSON file.

This script relies on the KFX Input plugin's `kfxlib` library (included in this
repository) to decode the KFX container. It converts the book into a JSON
structure with content and position information and then maps the annotation
positions directly onto that content.
"""
import argparse
import json
import sys
from pathlib import Path
from html import escape

# Make the bundled Calibre KFX Input plugin importable as kfxlib.
# The directory layout is: <repo>/KFX Input/kfxlib/...
# Falls back to the legacy .zip and to a kfxlib_extracted/ folder for
# back-compat with older clones.
base_dir = Path(__file__).parent
for candidate in (base_dir / "KFX Input", base_dir / "kfxlib_extracted", base_dir / "KFX Input.zip"):
    if candidate.exists():
        sys.path.insert(0, str(candidate))
        break
from kfxlib import yj_book
from kfxlib.ion import IonSymbol
from kfxlib.yj_container import YJFragment


def load_content_sections(kfx_path):
    """Return sorted list of text sections with position and length."""
    book = yj_book.YJ_Book(kfx_path)
    content_json = json.loads(book.convert_to_json_content().decode("utf-8"))

    sections = [e for e in content_json.get("data", []) if e.get("type") == 1]
    sections.sort(key=lambda x: x["position"])

    # Infer text length from next section's position
    for i, sec in enumerate(sections[:-1]):
        sec["length"] = sections[i + 1]["position"] - sec["position"]
    if sections:
        sections[-1]["length"] = len(sections[-1]["content"])
    return sections


def extract_text(sections, start, end):
    """Extract text between the given start and end positions."""
    parts = []
    # Find the first section that might contain the start position
    idx = 0
    while idx < len(sections) - 1 and sections[idx + 1]["position"] <= start:
        idx += 1

    # Collect text from overlapping sections
    while idx < len(sections) and sections[idx]["position"] < end:
        sec = sections[idx]
        sec_start = sec["position"]
        sec_end = sec_start + sec["length"]
        slice_start = max(start, sec_start)
        slice_end = min(end + 1, sec_end)
        if slice_end > slice_start:
            a = slice_start - sec_start
            b = slice_end - sec_start
            parts.append(sec["content"][a:b])
        idx += 1
    return "".join(parts).replace("\n", " ").strip()


def load_navigation(kfx_path):
    """Return (pages, toc) from the KFX navigation data."""
    book = yj_book.YJ_Book(kfx_path)
    book.decode_book(set_approximate_pages=0)

    nav = book.fragments.get("$389", first=True)
    if nav is None:
        return [], []

    pages = []
    toc_items = []

    pos_info = book.collect_content_position_info()
    eid_to_pid = {}
    for chunk in pos_info:
        if chunk.eid not in eid_to_pid:
            eid_to_pid[chunk.eid] = chunk.pid - chunk.eid_offset

    def unwrap(val):
        while hasattr(val, "value"):
            val = val.value
        if isinstance(val, dict):
            return {k: unwrap(v) for k, v in val.items()}
        elif isinstance(val, list):
            return [unwrap(v) for v in val]
        return val

    for container in nav.value[0].get("$392", []):
        data = unwrap(container)
        if isinstance(data, IonSymbol):
            container_frag = book.fragments.get(ftype="$391", fid=data)
            data = unwrap(container_frag) if container_frag else {}
        typ = data.get("$235")
        if typ == "$237":  # page list
            page_list = data.get("$247", [])
            for entry in page_list:
                pid = eid_to_pid.get(entry["$246"]["$155"], 0) + entry["$246"].get("$143", 0)
                label = entry["$241"]["$244"]
                pages.append((pid, label))
            pages.sort(key=lambda x: x[0])
        elif typ == "$212":  # toc
            def build_items(items):
                result = []
                for itm in items:
                    eid = itm["$246"]["$155"]
                    offset = itm["$246"].get("$143", 0)
                    pid = eid_to_pid.get(eid, 0) + offset
                    label = itm["$241"]["$244"]
                    node = {
                        "label": label,
                        "pid": pid,
                        "children": build_items(itm.get("$247", [])),
                    }
                    result.append(node)
                return result

            toc_items = build_items(data.get("$247", []))

    return pages, toc_items


def generate_html(title, authors, items, output_path, year=""):
    """Write highlights to an HTML file with simple Kindle Notebook styling."""
    style = """
        <style type="text/css">
            .bodyContainer {
                font-family: Arial, Helvetica, sans-serif;
                text-align: center;
                padding-left: 32px;
                padding-right: 32px;
            }
            .notebookFor {
                font-size: 18px;
                font-weight: 700;
                text-align: center;
                color: rgb(119, 119, 119);
                margin: 24px 0px 0px;
                padding: 0px;
            }
            .bookTitle {
                font-size: 32px;
                font-weight: 700;
                text-align: center;
                color: #333333;
                margin-top: 22px;
                padding: 0px;
            }
            .authors {
                font-size: 13px;
                font-weight: 700;
                text-align: center;
                color: rgb(119, 119, 119);
                margin-top: 22px;
                margin-bottom: 24px;
                padding: 0px;
            }
            .noteHeading {
                font-size: 18px;
                font-weight: 700;
                text-align: left;
                color: #333333;
                margin-top: 20px;
                padding: 0px;
            }
            .sectionHeading {
                font-size: 24px;
                font-weight: 700;
                text-align: left;
                color: #333333;
                margin-top: 24px;
                padding: 0px;
            }
            .highlight_yellow {
                color: rgb(247, 206, 0);
            }
            .noteText {
                font-size: 18px;
                font-weight: 500;
                text-align: left;
                color: #333333;
                margin: 2px 0px 0px;
                padding: 0px;
            }
            hr {
                border: 0px none;
                height: 1px;
                background: none repeat scroll 0% 0% rgb(221, 221, 221);
            }
        </style>
    """

    html_parts = [
        "<?xml version='1.0' encoding='UTF-8' ?>",
        "<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.0 Strict//EN'",
        "  'http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd'>",
        "<html xmlns='http://www.w3.org/TR/1999/REC-html-in-xml' xml:lang='en' lang='en'>",
        "<head>",
        "<meta charset='UTF-8' />",
        style,
        "<title></title>",
        "</head>",
        "<body>",
        "<div class='bodyContainer'>",
        "<div class='notebookFor'>Notebook for</div>",
        f"<div class='bookTitle'>{escape(title)}</div>",
        f"<div class='authors'>{escape(', '.join(authors))}</div>",
        "<div class='citation'>Citation (APA): {author} ({year}). <i>{t}</i> [Kindle version]. Retrieved from Amazon.com</div>".format(
            author=escape(authors[0]) if authors else "",
            year=escape(year),
            t=escape(title),
        ),
        "<hr />",
    ]

    current_section = None
    for item in items:
        if item.get("section") and item["section"] != current_section:
            html_parts.append(f"<div class='sectionHeading'>{escape(item['section'])}</div>")
            current_section = item["section"]

        meta_parts = []
        if item.get("chapter"):
            meta_parts.append(item["chapter"])
        if item.get("page"):
            meta_parts.append(f"Page {item['page']}")
        meta_str = " - " + " >  ".join(meta_parts) if meta_parts else ""

        text = escape(item.get("text", ""))
        if item.get("type") == "note":
            html_parts.append(f"<div class='noteHeading'>Note{meta_str}</div>")
        else:
            html_parts.append(
                f"<div class='noteHeading'>Highlight (<span class='highlight_yellow'>yellow</span>){meta_str}</div>"
            )
        html_parts.append(f"<div class='noteText'>{text}</div>")

    html_parts.extend(["</div>", "</body>", "</html>"])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))


def generate_markdown(title, authors, items, output_path, year=""):
    """Write highlights as Markdown, one section per chapter, quotes as blockquotes."""
    lines = [f"# {title}"]
    if authors:
        lines.append(f"_{', '.join(authors)}_")
    if year:
        lines.append(f"*{year}*")
    lines.append("")

    current_section = None
    for item in items:
        section = item.get("section")
        if section and section != current_section:
            lines.append("")
            lines.append(f"## {section}")
            lines.append("")
            current_section = section

        meta_parts = []
        if item.get("chapter"):
            meta_parts.append(item["chapter"])
        if item.get("page"):
            meta_parts.append(f"Page {item['page']}")
        meta_str = " — " + " > ".join(meta_parts) if meta_parts else ""

        if item.get("type") == "note":
            lines.append(f"**Note{meta_str}**")
        else:
            lines.append(f"**Highlight{meta_str}**")
        lines.append("")
        for txt_line in (item.get("text", "") or "").splitlines() or [item.get("text", "")]:
            lines.append(f"> {txt_line}")
        lines.append("")

    Path(output_path).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def generate_full_book_html(title, authors, sections, annotations, notes, toc, output_path, year=""):
    """Render the full book text with in-place highlights and sidebar margin notes."""
    # Build list of events across all sections
    # Flatten text positions across sections
    events = []  # (pos, type, payload)
    
    # 1. Highlights events
    for ann in annotations:
        start = int(ann["startPosition"].split(":")[1])
        end = int(ann["endPosition"].split(":")[1])
        events.append((start, "hl_start", None))
        events.append((end + 1, "hl_end", None))
        
    # 2. Notes events (indexed by position)
    for n in notes:
        pos = int(n["startPosition"].split(":")[1])
        events.append((pos, "note", n.get("note", "")))
        
    # 3. TOC Chapter heading positions (used to mark chapter break positions without duplicating text)
    toc_pids = set()
    def collect_toc_pids(items):
        for item in items:
            if item.get("pid") is not None:
                toc_pids.add(item["pid"])
            if item.get("children"):
                collect_toc_pids(item["children"])
    collect_toc_pids(toc)

    # Sort events by position. 
    # Order at same position: hl_end < hl_start < note
    type_order = {"hl_end": 0, "hl_start": 1, "note": 2}
    events.sort(key=lambda x: (x[0], type_order.get(x[1], 3)))
    
    # Construct full text stream with annotations inserted
    body_html = []
    
    # Build content offset map across sections
    # Join sections content while maintaining character position matching
    current_pos = 0
    event_idx = 0
    n_events = len(events)
    
    in_highlight = False
    
    in_paragraph = False
    hl_counter = 0
    note_counter = 0

    for sec in sections:
        sec_start = sec["position"]
        sec_end = sec_start + sec["length"]
        content = sec["content"]
        
        # Each text section in KFX content_json represents a distinct paragraph or structural unit
        if in_paragraph:
            body_html.append("</p>\n")
            in_paragraph = False
            
        # If this section start corresponds to a chapter/TOC position, insert a visual section divider
        if sec_start in toc_pids or sec_start == 0:
            body_html.append("<hr class='chapter-divider' />\n")

        # Start a new paragraph for this section
        body_html.append("<p dir='auto'>")
        in_paragraph = True

        # Advance events up to sec_start
        while event_idx < n_events and events[event_idx][0] < sec_start:
            ev_pos, ev_type, ev_val = events[event_idx]
            if ev_type == "hl_start":
                if not in_highlight:
                    body_html.append("<mark class='kfx-highlight'>")
                    in_highlight = True
            elif ev_type == "hl_end":
                if in_highlight:
                    body_html.append("</mark>")
                    in_highlight = False
            elif ev_type == "note" and ev_val:
                body_html.append(
                    f"<aside class='margin-note' dir='auto'><span class='note-icon'>📝</span> {escape(ev_val)}</aside>"
                )
            event_idx += 1

        sec_local_pos = 0
        # Track active highlight IDs to associate with notes
        active_hl_id = None
        
        while sec_local_pos < len(content):
            global_pos = sec_start + sec_local_pos
            
            # If internal character position hits a TOC chapter boundary, break paragraph and insert divider
            if global_pos in toc_pids and sec_local_pos > 0:
                if in_paragraph:
                    body_html.append("</p>\n")
                    in_paragraph = False
                body_html.append("<hr class='chapter-divider' />\n")
                body_html.append("<p dir='auto'>")
                in_paragraph = True
            
            # Check if there are events at global_pos
            while event_idx < n_events and events[event_idx][0] == global_pos:
                ev_pos, ev_type, ev_val = events[event_idx]
                if ev_type == "hl_start":
                    if not in_highlight:
                        hl_counter += 1
                        active_hl_id = f"hl-{hl_counter}"
                        body_html.append(f"<mark class='kfx-highlight' id='{active_hl_id}' data-hl-id='{active_hl_id}'>")
                        in_highlight = True
                elif ev_type == "hl_end":
                    if in_highlight:
                        body_html.append("</mark>")
                        in_highlight = False
                elif ev_type == "note" and ev_val:
                    note_counter += 1
                    note_id = f"note-{note_counter}"
                    target_hl = active_hl_id or f"hl-{hl_counter}"
                    # Insert superscript marker badge right at note position
                    body_html.append(
                        f"<sup class='note-marker' data-target-note='{note_id}' data-target-hl='{target_hl}'>[📝{note_counter}]</sup>"
                    )
                    # Insert sidebar note with matching data-target-hl attribute
                    body_html.append(
                        f"<aside class='margin-note' id='{note_id}' data-hl-id='{target_hl}' dir='auto'>"
                        f"<span class='note-num'>[{note_counter}]</span> <span class='note-icon'>📝</span> {escape(ev_val)}"
                        f"</aside>"
                    )
                event_idx += 1
                
            # Find next event position within this section
            next_event_pos = len(content)
            if event_idx < n_events and events[event_idx][0] < sec_end:
                next_event_pos = events[event_idx][0] - sec_start
                
            chunk = content[sec_local_pos:next_event_pos]
            if chunk:
                # Format paragraph breaks cleanly
                paragraphs = chunk.split("\n\n")
                for p_i, p in enumerate(paragraphs):
                    if p_i > 0:
                        body_html.append("</p>\n<p dir='auto'>")
                    # Replace single newlines with spaces within paragraph
                    body_html.append(escape(p.replace("\n", " ")))
            sec_local_pos = next_event_pos

    # Process any remaining events at the very end
    while event_idx < n_events:
        ev_pos, ev_type, ev_val = events[event_idx]
        if ev_type == "hl_end" and in_highlight:
            body_html.append("</mark>")
            in_highlight = False
        elif ev_type == "note" and ev_val:
            note_counter += 1
            note_id = f"note-{note_counter}"
            target_hl = f"hl-{hl_counter}"
            body_html.append(
                f"<sup class='note-marker' data-target-note='{note_id}' data-target-hl='{target_hl}'>[📝{note_counter}]</sup>"
            )
            body_html.append(
                f"<aside class='margin-note' id='{note_id}' data-hl-id='{target_hl}' dir='auto'>"
                f"<span class='note-num'>[{note_counter}]</span> <span class='note-icon'>📝</span> {escape(ev_val)}"
                f"</aside>"
            )
        event_idx += 1

    if in_highlight:
        body_html.append("</mark>")

    if in_paragraph:
        body_html.append("</p>")

    style = """
    <style>
        :root {
            --bg-color: #fcfcf9;
            --text-color: #2b2b2b;
            --highlight-bg: #fff3a3;
            --highlight-border: #f0cb00;
            --highlight-active-bg: #ffe066;
            --note-bg: #ffffff;
            --note-border: #3b82f6;
            --note-active-border: #1d4ed8;
            --note-active-bg: #eff6ff;
            --note-text: #1e3a8a;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Vazirmatn", "Noto Naskh Arabic", Georgia, serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            line-height: 1.8;
            font-size: 18px;
            margin: 0;
            padding: 40px 20px;
            display: flex;
            justify-content: center;
        }
        .container {
            max-width: 1100px;
            width: 100%;
            display: grid;
            grid-template-columns: minmax(0, 1fr) 320px;
            gap: 40px;
            position: relative;
        }
        .book-content {
            grid-column: 1;
        }
        .header {
            margin-bottom: 40px;
            padding-bottom: 20px;
            border-bottom: 2px solid #e5e7eb;
        }
        .book-title {
            font-size: 2.2rem;
            font-weight: 700;
            margin: 0 0 8px 0;
            color: #111827;
        }
        .book-authors {
            font-size: 1.1rem;
            color: #6b7280;
            margin: 0;
        }
        .chapter-heading {
            font-size: 1.6rem;
            font-weight: 600;
            margin-top: 48px;
            margin-bottom: 20px;
            color: #1f2937;
            border-bottom: 1px solid #f3f4f6;
            padding-bottom: 8px;
            text-align: start;
        }
        .chapter-divider {
            border: none;
            height: 1px;
            background: linear-gradient(to right, transparent, #d1d5db, transparent);
            margin: 48px 0 32px 0;
        }
        p {
            margin-bottom: 20px;
            text-align: start;
            unicode-bidi: plaintext;
        }
        p[dir="rtl"], .chapter-heading[dir="rtl"] {
            text-align: right;
        }
        mark.kfx-highlight {
            background-color: var(--highlight-bg);
            border-bottom: 2px solid var(--highlight-border);
            padding: 2px 0;
            border-radius: 2px;
            cursor: pointer;
            transition: background-color 0.2s, box-shadow 0.2s;
        }
        mark.kfx-highlight:hover, mark.kfx-highlight.active-link {
            background-color: var(--highlight-active-bg);
            box-shadow: 0 0 0 3px rgba(245, 158, 11, 0.4);
        }
        .note-marker {
            font-size: 0.75rem;
            font-weight: 700;
            color: #2563eb;
            cursor: pointer;
            margin: 0 2px;
            vertical-align: super;
            user-select: none;
            transition: color 0.15s, transform 0.15s;
        }
        .note-marker:hover {
            color: #1d4ed8;
            text-decoration: underline;
        }
        aside.margin-note {
            grid-column: 2;
            float: right;
            clear: right;
            margin-right: -360px;
            width: 320px;
            margin-top: -4px;
            margin-bottom: 16px;
            padding: 12px 16px;
            background: var(--note-bg);
            border-left: 4px solid var(--note-border);
            border-radius: 6px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
            font-size: 0.92rem;
            line-height: 1.5;
            color: var(--note-text);
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
            text-align: start;
            unicode-bidi: plaintext;
            cursor: pointer;
            transition: border-color 0.2s, background-color 0.2s, transform 0.2s, box-shadow 0.2s;
        }
        aside.margin-note[dir="rtl"] {
            border-left: none;
            border-right: 4px solid var(--note-border);
        }
        aside.margin-note:hover, aside.margin-note.active-link {
            background-color: var(--note-active-bg);
            border-left-color: var(--note-active-border);
            transform: translateX(4px);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05);
        }
        aside.margin-note[dir="rtl"]:hover, aside.margin-note[dir="rtl"].active-link {
            border-right-color: var(--note-active-border);
            transform: translateX(-4px);
        }
        .note-num {
            font-weight: 700;
            color: #2563eb;
            margin-right: 4px;
        }
        .note-icon {
            margin-right: 4px;
        }
        @media (max-width: 900px) {
            .container {
                display: block;
            }
            aside.margin-note {
                float: none;
                clear: both;
                margin-right: 0;
                width: auto;
                margin-top: 16px;
                margin-bottom: 16px;
            }
        }
    </style>
    """

    script = """
    <script>
    document.addEventListener("DOMContentLoaded", function () {
        // Handle hovering and clicking on highlights, note markers, and margin notes
        function clearActive() {
            document.querySelectorAll(".active-link").forEach(el => el.classList.remove("active-link"));
        }

        // Highlight -> Sidebar Note
        document.querySelectorAll("mark.kfx-highlight").forEach(hl => {
            const hlId = hl.getAttribute("data-hl-id");
            const note = document.querySelector(`aside.margin-note[data-hl-id='${hlId}']`);
            if (note) {
                hl.addEventListener("mouseenter", () => {
                    hl.classList.add("active-link");
                    note.classList.add("active-link");
                });
                hl.addEventListener("mouseleave", () => {
                    hl.classList.remove("active-link");
                    note.classList.remove("active-link");
                });
                hl.addEventListener("click", () => {
                    note.scrollIntoView({ behavior: "smooth", block: "center" });
                });
            }
        });

        // Sidebar Note -> Highlight
        document.querySelectorAll("aside.margin-note").forEach(note => {
            const hlId = note.getAttribute("data-hl-id");
            const hl = document.getElementById(hlId);
            if (hl) {
                note.addEventListener("mouseenter", () => {
                    note.classList.add("active-link");
                    hl.classList.add("active-link");
                });
                note.addEventListener("mouseleave", () => {
                    note.classList.remove("active-link");
                    hl.classList.remove("active-link");
                });
                note.addEventListener("click", () => {
                    hl.scrollIntoView({ behavior: "smooth", block: "center" });
                });
            }
        });

        // Note Marker Badge -> Sidebar Note & Highlight
        document.querySelectorAll(".note-marker").forEach(marker => {
            const noteId = marker.getAttribute("data-target-note");
            const hlId = marker.getAttribute("data-target-hl");
            const note = document.getElementById(noteId);
            const hl = document.getElementById(hlId);

            marker.addEventListener("mouseenter", () => {
                if (note) note.classList.add("active-link");
                if (hl) hl.classList.add("active-link");
            });
            marker.addEventListener("mouseleave", () => {
                if (note) note.classList.remove("active-link");
                if (hl) hl.classList.remove("active-link");
            });
            marker.addEventListener("click", () => {
                if (note) note.scrollIntoView({ behavior: "smooth", block: "center" });
            });
        });
    });
    </script>
    """

    html_out = [
        "<!DOCTYPE html>",
        "<html lang='en'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        f"<title>{escape(title)} - Full Book with Highlights</title>",
        style,
        "</head>",
        "<body>",
        "<div class='container'>",
        "<div class='book-content' dir='auto'>",
        "<div class='header'>",
        f"<h1 class='book-title' dir='auto'>{escape(title)}</h1>",
        f"<p class='book-authors' dir='auto'>{escape(', '.join(authors))}</p>",
        "</div>",
        "".join(body_html),
        "</div>",
        "</div>",
        script,
        "</body>",
        "</html>",
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_out))


def main():
    parser = argparse.ArgumentParser(description="Extract highlight text from a KFX book using a .yjr JSON file.")
    parser.add_argument("annotations_json", help="Path to the .yjr.json file produced by krds.py")
    parser.add_argument("book_kfx", help="Path to the .kfx book file")
    parser.add_argument(
        "--markdown", "-m",
        action="store_true",
        help="Emit a .highlights.md file (Markdown grouped by chapter) instead of .highlights.html",
    )
    parser.add_argument(
        "--full-book", "-f",
        action="store_true",
        help="Render the full book HTML with in-place highlights and sidebar margin notes",
    )
    args = parser.parse_args()

    json_file = args.annotations_json
    kfx_file = args.book_kfx

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    ann_obj = data.get("annotation.cache.object", {})
    annotations = ann_obj.get("annotation.personal.highlight", [])
    notes = ann_obj.get("annotation.personal.note", [])
    if not annotations and not notes:
        print("No highlights or notes found in annotation data.")
        return

    sections = load_content_sections(kfx_file)
    meta = yj_book.YJ_Book(kfx_file).get_metadata()
    pages, toc = load_navigation(kfx_file)

    def page_for_pid(pid):
        p = None
        for pp, label in pages:
            if pp <= pid:
                p = label
            else:
                break
        return p

    def find_section(pid):
        section = None
        chapter = None
        for sec in toc:
            if sec["pid"] <= pid:
                section = sec
            else:
                break
        if section:
            for ch in section.get("children", []):
                if ch["pid"] <= pid:
                    chapter = ch
                else:
                    break
        return (section["label"] if section else None,
                chapter["label"] if chapter else None)

    highlights = []
    notes_by_end = {}
    for n in notes:
        pos = int(n["startPosition"].split(":")[1])
        notes_by_end.setdefault(pos, []).append(n["note"])

    annotations.sort(key=lambda a: int(a["startPosition"].split(":")[1]))
    print(f"Found {len(annotations)} highlights:\n{'='*60}")
    for i, ann in enumerate(annotations, 1):
        start = int(ann["startPosition"].split(":")[1])
        end = int(ann["endPosition"].split(":")[1])
        text = extract_text(sections, start, end)
        page = page_for_pid(start)
        section, chapter = find_section(start)
        try:
            print(f"\nHighlight #{i}")
            print(f"Created: {ann['creationTime']}")
            print(f"Text: {text}\n{'-'*60}")
        except UnicodeEncodeError:
            print(f"Text: {text.encode('ascii', errors='backslashreplace').decode('ascii')}\n{'-'*60}")
        highlights.append({
            "creationTime": ann["creationTime"],
            "text": text,
            "page": page,
            "section": section,
            "chapter": chapter,
            "type": "highlight",
        })
        for note_text in notes_by_end.get(end, []):
            highlights.append({
                "creationTime": "",
                "text": note_text,
                "page": page,
                "section": section,
                "chapter": chapter,
                "type": "note",
            })

    year = ""
    if getattr(meta, "issue_date", None):
        year = str(meta.issue_date).split("-")[0]

    title = meta.title or Path(kfx_file).stem
    authors = meta.authors or []
    if args.full_book:
        output_path = Path(kfx_file).with_suffix(".full_book.html")
        generate_full_book_html(title, authors, sections, annotations, notes, toc, output_path, year)
        print(f"\nSaved Full Book HTML with inline highlights and sidebar notes to {output_path}")
    elif args.markdown:
        output_path = Path(kfx_file).with_suffix(".highlights.md")
        generate_markdown(title, authors, highlights, output_path, year)
        print(f"\nSaved Markdown highlights to {output_path}")
    else:
        output_path = Path(kfx_file).with_suffix(".highlights.html")
        generate_html(title, authors, highlights, output_path, year)
        print(f"\nSaved HTML highlights to {output_path}")


if __name__ == "__main__":
    main()
