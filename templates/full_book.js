document.addEventListener("DOMContentLoaded", function () {

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

    // TOC Link Click Smooth Scroll
    document.querySelectorAll(".toc-link").forEach(link => {
        link.addEventListener("click", (e) => {
            const targetId = link.getAttribute("data-target-id");
            if (targetId) {
                const target = document.getElementById(targetId);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({ behavior: "smooth", block: "start" });
                    history.pushState(null, null, `#${targetId}`);
                }
            }
        });
    });

    // TOC Active Chapter Highlight on Scroll (ScrollSpy)
    const tocLinks = Array.from(document.querySelectorAll(".toc-link[data-target-id]"));
    if (tocLinks.length > 0) {
        const chapterDividers = tocLinks
            .map(link => document.getElementById(link.getAttribute("data-target-id")))
            .filter(Boolean);

        function updateActiveToc() {
            const scrollPos = window.scrollY + 100;
            let currentCh = null;

            for (let i = 0; i < chapterDividers.length; i++) {
                const div = chapterDividers[i];
                if (div.offsetTop <= scrollPos) {
                    currentCh = div.id;
                } else {
                    break;
                }
            }

            tocLinks.forEach(link => {
                if (currentCh && link.getAttribute("data-target-id") === currentCh) {
                    link.classList.add("active");
                } else {
                    link.classList.remove("active");
                }
            });
        }

        window.addEventListener("scroll", updateActiveToc, { passive: true });
        updateActiveToc();
    }
});
