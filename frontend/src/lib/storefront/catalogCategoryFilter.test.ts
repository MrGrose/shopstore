import { describe, expect, it } from "vitest";

import type { CatalogTaxonomy } from "./catalog";
import {
  sportLabelFromTaxonomy,
  subcategoriesFromTaxonomy,
  taxonomyUsesMappingSections,
} from "./catalogCategoryFilter";
import { CATALOG_ALL_LABEL_RU } from "./catalogNavigation";

const taxonomy: CatalogTaxonomy = {
  sports: [
    {
      sport: "Tennis",
      slug: "tennis",
      label: "Теннис",
      sections: [
        {
          slug: "accessories",
          label: "Аксессуары",
          chips: [
            {
              display_key: "tennis.accessories.overgrips",
              slug: "overgrips",
              label: "Овергрипы",
            },
          ],
        },
      ],
      subcategories: [],
    },
  ],
  sub_slug_aliases: {},
};

describe("catalogCategoryFilter public labels", () => {
  it("uses taxonomy label for sport tabs", () => {
    expect(sportLabelFromTaxonomy(taxonomy, "Tennis")).toBe("Теннис");
  });

  it("maps section/chip labels from taxonomy without legacy keys", () => {
    const rows = subcategoriesFromTaxonomy(taxonomy, "tennis");
    expect(rows[0]?.label).toBe("Аксессуары");
    expect(rows[0]?.types[0]?.label_ru).toBe("Овергрипы");
    expect(rows[0]?.types[0]?.label_ru).not.toBe("tennis.accessories.overgrips");
  });

  it("keeps All catalog title in Russian", () => {
    expect(CATALOG_ALL_LABEL_RU).toBe("Все товары");
  });

  it("detects mapping sections from taxonomy", () => {
    expect(taxonomyUsesMappingSections(taxonomy, "tennis")).toBe(true);
    expect(taxonomyUsesMappingSections(null, "tennis")).toBe(false);
  });
});
