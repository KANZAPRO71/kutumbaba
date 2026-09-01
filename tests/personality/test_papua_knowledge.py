"""Tests for Papua knowledge base retrieval."""

from __future__ import annotations

from persona_ai.personality.papua_knowledge import (
    core_knowledge_facts,
    knowledge_prompt_lines,
    retrieve_knowledge_facts,
    topic_count,
)


class TestPapuaKnowledge:
    def test_core_facts_loaded(self):
        facts = core_knowledge_facts()
        assert len(facts) >= 4
        assert any("Jayapura" in f for f in facts)

    def test_retrieve_jayapura(self):
        facts = retrieve_knowledge_facts("Ko tau tentang Jayapura dan Sentani?")
        assert facts
        joined = " ".join(facts).lower()
        assert "jayapura" in joined or "sentani" in joined

    def test_retrieve_sagu(self):
        facts = retrieve_knowledge_facts("makanan sagu papeda")
        assert facts
        assert any("sagu" in f.lower() or "papeda" in f.lower() for f in facts)

    def test_empty_query_no_retrieve(self):
        assert retrieve_knowledge_facts("") == []
        assert retrieve_knowledge_facts(None) == []

    def test_knowledge_prompt_papua_dialect(self):
        lines = knowledge_prompt_lines("papua", include_core=True)
        assert any("Pengetahuan Papua" in line for line in lines)
        assert any("Fakta inti" in line for line in lines)

    def test_knowledge_prompt_with_query(self):
        lines = knowledge_prompt_lines(
            "papua",
            query="Raja Ampat diving",
            include_core=False,
        )
        text = "\n".join(lines).lower()
        assert "raja ampat" in text or "sorong" in text

    def test_knowledge_prompt_skipped_non_papua(self):
        assert knowledge_prompt_lines(None) == []
        assert knowledge_prompt_lines("jakarta") == []

    def test_retrieve_timika(self):
        facts = retrieve_knowledge_facts("kerja di timika freeport mimika")
        assert facts
        text = " ".join(facts).lower()
        assert "timika" in text or "mimika" in text

    def test_retrieve_biak(self):
        facts = retrieve_knowledge_facts("bahasa biak pulau")
        assert facts
        assert any("biak" in f.lower() for f in facts)

    def test_retrieve_suku_dani(self):
        facts = retrieve_knowledge_facts("suku dani honai koteka")
        assert facts
        assert any("dani" in f.lower() or "honai" in f.lower() for f in facts)

    def test_topic_count(self):
        assert topic_count() >= 40

    def test_retrieve_legenda(self):
        facts = retrieve_knowledge_facts("legenda danau sentani cerita rakyat")
        assert facts
        assert any("sentani" in f.lower() or "legenda" in f.lower() for f in facts)

    def test_retrieve_tolikara(self):
        facts = retrieve_knowledge_facts("tolikara karubaga yali")
        assert facts
        assert any("tolikara" in f.lower() or "karubaga" in f.lower() for f in facts)

    def test_retrieve_persipura_boaz(self):
        facts = retrieve_knowledge_facts("Persipura Jayapura Boaz Solossa")
        assert facts
        text = " ".join(facts).lower()
        assert "persipura" in text or "boaz" in text

    def test_retrieve_salam_lokal(self):
        facts = retrieve_knowledge_facts("salam amolongo aosiafa pace mace")
        assert facts
        text = " ".join(facts).lower()
        assert "pace" in text or "aosiafa" in text or "amolongo" in text

    def test_retrieve_pantai_pegunungan(self):
        facts = retrieve_knowledge_facts("beda pantai pesisir dan pegunungan lapago")
        assert facts
        text = " ".join(facts).lower()
        assert "pesisir" in text or "pegunungan" in text or "honai" in text

    def test_retrieve_wilayah_adat(self):
        facts = retrieve_knowledge_facts("wilayah adat Mamta Saireri La Pago")
        assert facts
        text = " ".join(facts).lower()
        assert "mamta" in text or "saireri" in text or "pago" in text

    def test_retrieve_noken(self):
        facts = retrieve_knowledge_facts("noken unesco warisan budaya")
        assert facts
        joined = " ".join(facts).lower()
        assert "noken" in joined
        assert "unesco" in joined or "rahm" in joined or "kepala" in joined

    def test_retrieve_barapen(self):
        facts = retrieve_knowledge_facts("barapen kit oba isago bakar batu")
        assert facts
        text = " ".join(facts).lower()
        assert "barapen" in text or "bakar batu" in text or "kit oba" in text

    def test_retrieve_ararem(self):
        facts = retrieve_knowledge_facts("ararem biak piring gantung maskawin")
        assert facts
        text = " ".join(facts).lower()
        assert "ararem" in text or "piring" in text or "biak" in text

    def test_retrieve_iki_palek(self):
        facts = retrieve_knowledge_facts("iki palek dani potong jari")
        assert facts
        text = " ".join(facts).lower()
        assert "iki palek" in text or "jari" in text or "dani" in text

    def test_retrieve_lima_pilar(self):
        facts = retrieve_knowledge_facts("lima pilar budaya papua noken asmat")
        assert facts
        text = " ".join(facts).lower()
        assert "noken" in text or "asmat" in text or "barapen" in text

    def test_retrieve_lukas_enembe(self):
        facts = retrieve_knowledge_facts("stadion Lukas Enembe Persipura")
        assert facts
        text = " ".join(facts).lower()
        assert "lukas" in text or "persipura" in text
