        self.assertEqual(payload["answer"], "Краткий ответ")
        self.assertEqual(row["duration_ms"], 42)

    def test_answer_over_8000_characters_is_preserved_in_encrypted_journal(self):
        family_id = tenancy.create_family("Long answer journal test", 9002)
        long_answer = "Б" * 9500
        ai_interaction_log.record(family_id=family_id, actor_id=9002,
            query="Длинный ответ", answer=long_answer, mode="analysis",
            provider="test-provider", model="test-model")
        with tenancy.connect() as conn:
            row = conn.execute("SELECT payload_enc FROM ai_interaction_logs WHERE family_id=?", (family_id,)).fetchone()
        payload = json.loads(tenancy.cipher().decrypt(bytes(row["payload_enc"])).decode())
        self.assertEqual(len(payload["answer"]), 9500)
        self.assertEqual(payload["answer"], long_answer)

if __name__ == "__main__":
    unittest.main()