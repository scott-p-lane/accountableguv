# Extending the dashboard directory

`table-4.html#dashboard` is the Table 4 directory. It links to dedicated dashboard pages; it does not load Tableau embeds itself.

## Add a dashboard

1. Create a dedicated HTML page (use `../net-income.html` as an example), linking to `mts.css` with the correct relative path.
2. Add its title, introduction, and one or more `dashboard-panel` sections. Each section needs unique heading, help, and `tableau-viz` IDs, and an `aria-labelledby` that matches its heading.
3. Load the Tableau v3 module and `../tableau-dashboards.js` once per page. Add the dashboard's Tableau embed URL and public sharing URL to the shared registry using a stable identifier, then use that identifier as `data-tableau-dashboard` on the `tableau-viz` and direct-link elements. The registry assigns the embed URL to the viz and the sharing URL to the direct link.
4. Add a `dashboard-tile` link inside the directory's `dashboard-directory` grid. Point it at the dedicated page, provide a title and summary with unique IDs, and update its thumbnail. Tableau Public's preview URL follows `https://public.tableau.com/static/images/WORKBOOK_FIRST_TWO_CHARACTERS/WORKBOOK/VIEW/1.png`. Verify that the image loads. A local screenshot can also be used.
5. Keep thumbnail alt text empty when it repeats the linked title; keep the title and summary readable if the image fails.

Load the shared registry with `<script defer src="../tableau-dashboards.js"></script>` (use `tableau-dashboards.js` for pages at the site root). It is a classic script; `defer` lets it assign links after the HTML has been parsed, including during local file previews. Keep Tableau's embedding API script as `type="module"`.

Use `https://public.tableau.com/views/WORKBOOK/VIEW?:showVizHome=no` for `embed`, and the public `/app/profile/.../viz/WORKBOOK/VIEW` URL for `share`. These are different URL formats. Changes are applied at runtime; they do not rewrite the HTML source. For a full Tableau preview, serve the site over HTTP.

When publishing registry changes, upload `tableau-dashboards.js` as well as any changed HTML. The site's CloudFront distribution caches files for one hour by default; invalidate `/tableau-dashboards.js` (and changed HTML paths) for immediate updates. Query-string version suffixes do not bypass this distribution's cache. A browser hard refresh alone does not clear CloudFront's cache.

## Add views to Net Income

Add quarterly/monthly views as additional sections in `../net-income.html`, with their own embed, narrative, and direct link. Add their section anchors to the “Dashboard views” navigation. Update the directory tile summary and remove the planned-views sentence when those views are available. Do not publish empty embeds or links for views that do not exist yet.

## Verify

Check thumbnail loading, whole-tile navigation with mouse and keyboard, unique IDs and working local anchors, dashboard rendering, and desktop/phone widths. Retain the field dictionary and its existing anchors below the directory.
