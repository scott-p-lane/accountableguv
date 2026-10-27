# Publishing a dedicated dashboard page

Each published Tableau dashboard has its own HTML page. `../us-income-and-spending.html` is the dashboard directory; `../us-net-income.html` is the first dashboard and the reusable page template.

## Create the next page

1. Copy `static content/us-net-income.html` to a new descriptive filename in `static content/`. Keep one published dashboard per page. Keeping the file at the site root preserves the template's relative asset and navigation paths.
2. Update the document title, description, main heading, introduction, dashboard heading, and accessible dashboard label.
3. Paste the supplied Tableau sharing link into the “Open in Tableau Public” anchor. Set the `tableau-viz` `src` to the same workbook and view using the embed format `https://public.tableau.com/views/WORKBOOK/VIEW?:showVizHome=no`. Both URLs are deliberately stored directly in the HTML page. The template loads Tableau's v3 module once and does not need the shared URL registry.
4. Replace the “Notes and observations” content with reading guidance and reviewed findings for that dashboard. Include reporting periods, filters, and comparison context. Leave a clear empty-state sentence until observations are ready; do not invent findings.
5. Update “Data sources and processing” with the exact source tables, field definitions, collection, validation, transformation, storage, export, and refresh documentation used. Distinguish source processing from workbook calculations and filters.
6. Update “Related pages” with relevant guides and analyses. Retain a return link to the dashboard directory.
7. Add a `dashboard-tile` to `us-income-and-spending.html`, with a title, summary, and image. Use unique heading and summary IDs. Add a link from any relevant source-table directory, such as `mts/table-4.html#dashboard`. Link directly to the dedicated dashboard page.
8. Keep thumbnail alt text empty when the image repeats the linked title. Use a relevant local illustration or an up-to-date verified dashboard preview. Do not imply illustrative graphics are actual data.

## Layout

The shared `mts/mts.css` provides a wide `.dashboard-page` main area, an embedded `.dashboard-panel`, and `.dashboard-detail` sections beneath it. The dashboard has its own scrollable viewport on smaller screens. The page's anchor navigation links to the dashboard, notes, sources, and related pages.

## Verify and publish

Check local links and anchors, unique IDs, matching Tableau workbook/view URLs, and descriptive headings. Serve the site over HTTP to verify the live Tableau embed, filters, direct link, keyboard navigation, and desktop/phone layout. An accessible direct link remains available if the embed fails or JavaScript is disabled.

Publish the new page, updated directory and source-table links, and any changed styles or images. CloudFront caches static files; invalidate changed paths when immediate updates are needed.
