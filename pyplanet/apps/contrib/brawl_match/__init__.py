from pyplanet.apps.config import AppConfig
from pyplanet.contrib.command import Command
from pyplanet.apps.contrib.brawl_match.views import BrawlMapListView


class BrawlMatch(AppConfig):
	game_dependencies = ['trackmania']
	app_dependencies = ['core.maniaplanet', 'core.trackmania']
	brawl_maps = [
		('26yU1ouud7IqURhbmlEzX3jxJM1', 49000), # On the Run
		('I5y9YjoVaw9updRFOecqmN0V6sh', 73000), # Moon Base
		('WUrcV1ziafkmDOEUQJslceNghs2', 72000), # Nos Astra
		('DPl6mjmUhXhlXqhpva_INcwvx5e', 55000), # Maru
		('3Pg4di6kaDyM04oHYm5AkC3r2ch', 46000), # Aliens Exist
		('ML4VsiZKZSiWNkwpEdSA11SH7mg', 51000), # L v g v s
		('GuIyeKb7lF6fsebOZ589d47Pqnk', 64000)  # Only a wooden leg remained
	]
	match_maps = brawl_maps

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)


	async def on_init(self):
		await super().on_init()



	async def on_start(self):
		print("BrawlMatch is starting")



		# Registering permissions
		await self.instance.permission_manager.register(
			'match_start',
			'Starting brawl matches',
			app=self,
			min_level=2
		)

		# Registering commands
		await self.instance.command_manager.register(
			Command(
				'match',
				target=self.command_match,
				admin=True
			)
		)

	async def command_match(self, player, *args, **kwargs):
		await self.set_match_settings()
		await self.choose_maps()


	async def set_match_settings(self):
		await self.instance.mode_manager.set_next_script('Cup.Script.txt')
		await self.instance.gbx('RestartMap')

		settings = await self.instance.mode_manager.get_settings()
		settings['S_AllowRespawn'] = True
		# Finish timeout will be set later
		settings['S_NbOfPlayersMax'] = 4
		settings['S_NbOfPlayersMin'] = 2
		settings['S_NbOfWinners'] = 2
		settings['S_PointsLimit'] = 70
		settings['S_PointsRepartition'] = '10,6,4,3'
		settings['S_RoundsPerMap'] = 3
		settings['S_WarmUpNb'] = 1
		await self.instance.mode_manager.update_settings(settings)

	async def update_finish_timeout_and_wu_duration(self, timeout, duration):
		settings = await self.instance.mode_manager.get_settings()
		settings['S_FinishTimeout'] = timeout
		settings['S_WarmUpDuration'] = duration
		await self.instance.mode_manager.update_next_settings(settings)

	async def choose_maps(self):
		maps = [map[0] for map in self.brawl_maps]
		view = BrawlMapListView(self, maps)
		await view.display(player='astronautj')

	async def ban_map(self, map):
		del self.match_maps[map]

