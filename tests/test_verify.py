from agent.verify import LITERAL, SWAPPED, UNVERIFIED, title_tokens, variant_swap, verify_copy


def item(title, description):
    return {"title": title, "description": description}


NUT_M8 = item("API_NUT_M8_ISO4032", "Hex nut M8 ISO 4032, zinc plated")
BOLT = item("API_BOLT_M8X25_ISO4017", "Hex bolt M8x25 ISO 4017, zinc plated")


def test_title_tokens_split_on_any_separator():
    assert title_tokens("SWC-Upper Washer sprinkler") == ["SWC", "Upper", "Washer", "sprinkler"]
    assert title_tokens("API_NUT_M8_ISO4032") == ["API", "NUT", "M8", "ISO4032"]


def test_variant_swap_replaces_the_tokens_the_titles_differ_in():
    assert variant_swap(NUT_M8["description"], NUT_M8["title"], "API_NUT_M6_ISO4032") == "Hex nut M6 ISO 4032, zinc plated"
    assert variant_swap(BOLT["description"], BOLT["title"], "API_BOLT_M6X16_ISO4017") == "Hex bolt M6x16 ISO 4017, zinc plated"
    # CAD style: spaces and hyphens
    assert variant_swap("Washer Upper - 23mm", "SWC-Upper Washer sprinkler", "SWC-Lower Washer sprinkler") == "Washer Lower - 23mm"


def test_variant_swap_refuses_what_it_cannot_justify():
    assert variant_swap("Hex nut M8", "API_NUT_M8", "API_NUT_M8") is None  # same title: nothing to swap
    assert variant_swap("Swingarm", "SWC-Swingarm sprinkler", "SWC-Upper Bearing sprinkler") is None  # 1 vs 2 tokens
    # The titles differ in Plate/Tag, but the description never says "Plate": the copy may not apply
    assert variant_swap("Top cap label", "SWC-Name Plate sprinkler", "SWC-Name Tag sprinkler") is None


def test_verify_copy_kinds():
    sources = [NUT_M8, BOLT]
    assert verify_copy("hex nut m8 iso 4032 zinc plated", "API_NUT_M8_ISO4032", "description", sources) == (LITERAL, NUT_M8["title"])
    assert verify_copy("Hex nut M6 ISO 4032, zinc plated", "API_NUT_M6_ISO4032", "description", sources) == (SWAPPED, NUT_M8["title"])
    assert verify_copy("Hex nut M6, stainless", "API_NUT_M6_ISO4032", "description", sources) == (UNVERIFIED, None)


def test_unapproved_ai_values_are_not_sources():
    proposed = item("API_NUT_M8_ISO4032", "[PROPOSED] Hex nut M8 ISO 4032")
    assert verify_copy("Hex nut M6 ISO 4032", "API_NUT_M6_ISO4032", "description", [proposed]) == (UNVERIFIED, None)
