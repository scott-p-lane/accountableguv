# Extending the dashboard directory

`table-4.html#dashboard` is the Table 4 directory. It links to dedicated dashboard pages; it does not load Tableau embeds itself.

## Add a dashboard

1. Create a dedicated HTML page (use `../net-income.html` as an example), linking to `mts.css` with the correct relative path.
2. Add its title, introduction, and one or more `dashboard-panel` sections. Each section needs unique heading, help, and `tableau-viz` IDs, and an `aria-labelledby` that matches its heading.
3. Load the Tableau v3 module once per page. Use `https://public.tableau.com/views/WORKBOOK/VIEW` for the embed; use the public sharing URL for the direct link. Keep the direct link and JavaScript fallback.
4. Add a `dashboard-tile` link inside the directory's `dashboard-directory` grid. Point it at the dedicated page, provide a title and summary with unique IDs, and update its thumbnail. Tableau Public's preview URL follows `https://public.tableau.com/static/images/WORKBOOK_FIRST_TWO_CHARACTERS/WORKBOOK/VIEW/1.png`. Verify that the image loads. A local screenshot can also be used.
5. Keep thumbnail alt text empty when it repeats the linked title; keep the title and summary readable if the image fails.

## Add views to Net Income

Add quarterly/monthly views as additional sections in `../net-income.html`, with their own embed, narrative, and direct link. Add their section anchors to the “Dashboard views” navigation. Update the directory tile summary and remove the planned-views sentence when those views are available. Do not publish empty embeds or links for views that do not exist yet.

## Verify

Check thumbnail loading, whole-tile navigation with mouse and keyboard, unique IDs and working local anchors, dashboard rendering, and desktop/phone widths. Retain the field dictionary and its existing anchors below the directory.
