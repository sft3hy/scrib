import unittest
import os
import sqlite3
from pathlib import Path
from screendoc import db

class TestDatabase(unittest.TestCase):
    def setUp(self):
        # Override DB_PATH for testing
        self.test_db_path = Path("output/test_scrib.db")
        db.DB_PATH = self.test_db_path
        if self.test_db_path.exists():
            self.test_db_path.unlink()
        db.init_db()

    def tearDown(self):
        if self.test_db_path.exists():
            self.test_db_path.unlink()

    def test_mock_user_seeded(self):
        user = db.get_user_by_id(1)
        self.assertIsNotNone(user)
        self.assertEqual(user["email"], "user@example.com")
        self.assertEqual(user["onboarding_completed"], 0)

    def test_onboarding_update(self):
        success = db.update_user_onboarding(1, True, "testing_reason")
        self.assertTrue(success)
        user = db.get_user_by_id(1)
        self.assertEqual(user["onboarding_completed"], 1)
        self.assertEqual(user["onboarding_reason"], "testing_reason")

    def test_guide_crud(self):
        # Create
        guide_id = db.create_guide(1, "Test Guide", "This is a test description")
        self.assertIsNotNone(guide_id)
        
        # Read
        guide = db.get_guide_by_id(guide_id)
        self.assertEqual(guide["title"], "Test Guide")
        self.assertEqual(guide["description"], "This is a test description")
        self.assertEqual(len(guide["steps"]), 0)

        # Update
        success = db.update_guide(guide_id, "Updated Test Guide", "Updated desc")
        self.assertTrue(success)
        guide = db.get_guide_by_id(guide_id)
        self.assertEqual(guide["title"], "Updated Test Guide")

        # Delete
        success = db.delete_guide(guide_id)
        self.assertTrue(success)
        guide = db.get_guide_by_id(guide_id)
        self.assertIsNone(guide)

    def test_steps(self):
        guide_id = db.create_guide(1, "Step Test Guide")
        
        # Add Steps
        step1_id = db.create_step(guide_id, 0, "Click Button", "/url/1.png", 10.5, 20.5)
        step2_id = db.create_step(guide_id, 1, "Type Text", "/url/2.png", 0, 0)
        
        # Verify Guide step retrieval
        guide = db.get_guide_by_id(guide_id)
        self.assertEqual(len(guide["steps"]), 2)
        self.assertEqual(guide["steps"][0]["caption"], "Click Button")
        self.assertEqual(guide["steps"][0]["click_x_percent"], 10.5)
        
        # Update Step
        success = db.update_step(step1_id, "New Click Button Caption", 0)
        self.assertTrue(success)
        
        # Delete Step and verify reordering
        success = db.delete_step(step1_id)
        self.assertTrue(success)
        
        guide = db.get_guide_by_id(guide_id)
        self.assertEqual(len(guide["steps"]), 1)
        self.assertEqual(guide["steps"][0]["id"], step2_id)
        self.assertEqual(guide["steps"][0]["order_index"], 0) # Correctly adjusted

if __name__ == "__main__":
    unittest.main()
