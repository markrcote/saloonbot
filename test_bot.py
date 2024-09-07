import os
import unittest
from unittest.mock import patch, AsyncMock, MagicMock

os.putenv('DISCORD_TOKEN', 'test_token')
print(os.getenv('DISCORD_TOKEN'))
from bot import determine_player_name, bot, card_game
print('bot loaded')

class TestBot(unittest.TestCase):
    def setUp(self):
        self.interaction = MagicMock()
        self.interaction.user.name = "TestUser"

    def test_determine_player_name_with_empty_player(self):
        player_name = determine_player_name(self.interaction, '')
        self.assertEqual(player_name, "TestUser")

    def test_determine_player_name_with_non_empty_player(self):
        player_name = determine_player_name(self.interaction, 'Player1')
        self.assertEqual(player_name, 'Player1')

    # @patch('builtins.print')
    # async def test_on_ready(self, mock_print):
    #     await bot.on_ready()
    #     mock_print.assert_called_once_with('Howdy folks.')

    # @patch('bot.git_sha', 'test_sha')
    # async def test_wwname_version(self):
    #     interaction = AsyncMock()
    #     await bot.get_command('wwname_version')(interaction)
    #     interaction.send.assert_called_once_with('test_sha')

    # @patch('bot.WildWestNames')
    # async def test_wwname(self, MockWildWestNames):
    #     interaction = AsyncMock()
    #     mock_names = MockWildWestNames.return_value
    #     mock_names.random_name.return_value = "TestName"
    #     await bot.get_command('wwname')(interaction, gender='', number=1)
    #     interaction.send.assert_called_once_with("TestName")

    # @patch.object(card_game, 'deal')
    # async def test_deal(self, mock_deal):
    #     interaction = AsyncMock()
    #     await bot.get_command('deal')(interaction, number=1, player='')
    #     mock_deal.assert_called_once_with("TestUser", 1)
    #     interaction.send.assert_called_once()


if __name__ == '__main__':
    unittest.main()
