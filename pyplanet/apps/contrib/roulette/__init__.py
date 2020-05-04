import asyncio
import random

from pyplanet.apps.config import AppConfig
from pyplanet.apps.contrib.roulette.views import SettingsListView
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.contrib.command import Command

class Roulette(AppConfig):
	game_dependencies = ['trackmania']
	app_dependencies = ['core.maniaplanet', 'core.trackmania']

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.settings = {
			'interval': -1,
			'sentences': []
		}
		self.settings_updated = False

	async def on_start(self):
		# Registering permissions
		await self.instance.permission_manager.register(
			'roulette_request',
			'Requesting a roulette output',
			app=self,
			min_level=0
		)

		await self.instance.permission_manager.register(
			'roulette_change_settings',
			'Changing settings of roulette',
			app=self,
			min_level=2
		)

		# Registering commands
		await self.instance.command_manager.register(
			Command(
				'roulette',
				target=self.handle_roulette_request,
				perms='brawl_match:roulette_request',
				admin=False
			),
			Command(
				'settings',
				namespace='roulette',
				target=self.handle_roulette_change_settings,
				perms='brawl_match:roulette_change_settings',
				admin=True
			)
		)

		self.automatic_roulette()

	async def automatic_roulette(self):
		if self.settings['interval'] > 0:
		while not self.settings_updated:
			self.roulette()
			asyncio.sleep(self.settings['interval'])

	async def handle_roulette_request(self, player, *args, **kwargs):
		self.roulette()


	async def roulette(self):
		self.instance.chat('$fff' + random.choice(self.settings['sentences']))

	async def handle_roulette_change_settings(self):
		settings_view = SettingsListView(self)
