import unittest
from unittest.mock import patch
from wwnames import WildWestNames


class TestWildWestNames(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.wild_west_names = WildWestNames()

    @patch('random.choice')
    def test_random_name_male(self, mock_choice):
        mock_choice.side_effect = ['John', 'Doe']
        result = self.wild_west_names.random_name(gender='M')
        self.assertEqual(result, '♂ John Doe')

    @patch('random.choice')
    def test_random_name_female(self, mock_choice):
        mock_choice.side_effect = ['Jane', 'Smith']
        result = self.wild_west_names.random_name(gender='F')
        self.assertEqual(result, '♀ Jane Smith')

    @patch('random.choice')
    def test_random_name_random_gender(self, mock_choice):
        mock_choice.side_effect = ['F', 'Mary', 'Brown']
        result = self.wild_west_names.random_name()
        self.assertEqual(result, '♀ Mary Brown')

    @patch('random.choice')
    def test_multiple_random_name_random_gender(self, mock_choice):
        mock_choice.side_effect = ['F', 'Mary', 'Brown', 'M', 'Aiden', 'Patel']
        result = self.wild_west_names.random_name(number=2)
        self.assertEqual(result, '♀ Mary Brown\n♂ Aiden Patel')


if __name__ == '__main__':
    unittest.main()
