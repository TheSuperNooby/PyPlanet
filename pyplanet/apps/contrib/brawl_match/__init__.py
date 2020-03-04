from pyplanet.apps.config import AppConfig
from pyplanet.contrib.command import Command
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.apps.core.maniaplanet.models import Map, Player
from pyplanet.apps.contrib.brawl_match.views import *
import asyncio
import random
import time


class BrawlMatch(AppConfig):
	game_dependencies = ['trackmania']
	app_dependencies = ['core.maniaplanet', 'core.trackmania']
	brawl_maps = [
		('26yU1ouud7IqURhbmlEzX3jxJM1', 49), # On the Run
		('I5y9YjoVaw9updRFOecqmN0V6sh', 73), # Moon Base
		('WUrcV1ziafkmDOEUQJslceNghs2', 72), # Nos Astra
		('DPl6mjmUhXhlXqhpva_INcwvx5e', 55), # Maru
		('3Pg4di6kaDyM04oHYm5AkC3r2ch', 46), # Aliens Exist
		('ML4VsiZKZSiWNkwpEdSA11SH7mg', 51), # L v g v s
		('GuIyeKb7lF6fsebOZ589d47Pqnk', 64)  # Only a wooden leg remained
	]
	match_maps = brawl_maps
	match_players = []
	chat_prefix = '$f33Brawl$fff - '

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.ban_queue = asyncio.Queue()


	async def on_init(self):
		await super().on_init()


	async def on_start(self):
		# Registering permissions
		await self.instance.permission_manager.register(
			'match_control',
			'Starting/Ending brawl matches',
			app=self,
			min_level=2
		)

		# Registering commands
		await self.instance.command_manager.register(
			Command(
				'match',
				target=self.command_match,
				perms='brawl_match:match_control',
				admin=True
			),
			Command(
				'matchend',
				target=self.stop_match,
				perms='brawl_match:match_control',
				admin=True
			)

		)


	async def command_match(self, player, *args, **kwargs):
		await self.set_match_settings()
		await self.instance.chat(self.chat_prefix + 'You started a brawl match. '
							   'Pick the participants from worst to best seed.', player)
		await self.choose_players(player=player)

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


	async def choose_players(self, player):
		player_view = BrawlPlayerListView(self)
		await player_view.display(player=player)


	async def add_player_to_match(self, admin, player_info):
		self.match_players.append(player_info['login'])
		await self.instance.chat(f'{self.chat_prefix}Player {player_info["nickname"]}$z$fff is added to the match.', admin)


	async def start_ban_phase(self):
		event_loop = asyncio.get_running_loop()
		for player in self.match_players:
			event_loop.call_soon_threadsafe(self.ban_queue.put_nowait, player)

		nicks = [(await Player.get_by_login(player)).nickname for player in self.match_players]
		nicks_string = '$z$fff vs '.join(nicks)
		await self.instance.chat(f'{self.chat_prefix}New match has been created: {nicks_string}$z$fff.')

		await self.instance.chat(f'{self.chat_prefix}Banning order:')
		for index, nick in enumerate(nicks, start=1):
			None
			# TODO - Code this
			# await self.instance.chat(f'{self.chat_prefix}[{index}/{len(nicks)}] {nick}')

		await self.next_ban()


	async def next_ban(self):
		if len(self.match_maps) > 3:
			player_to_ban = await self.ban_queue.get()
			player_nick = (await Player.get_by_login(player_to_ban)).nickname
			await self.instance.chat(f'{self.chat_prefix}Player {player_nick}$z$fff is now banning.')
			await self.ban_map(player_to_ban)
		else:
			await self.start_match()


	async def ban_map(self, player):
		maps = [map[0] for map in self.match_maps]
		ban_view = BrawlMapListView(self, maps)
		await ban_view.display(player=player)


	async def remove_map_from_match(self, map_info):
		self.match_maps.pop(map_info['index']-1)


	async def start_match(self):
		self.context.signals.listen(mp_signals.map.map_begin, self.set_settings_next_map)
		await self.shuffle_maps()

		maps = [(await Player.get_by_login(player)).nickname for player in self.match_players]
		await self.instance.chat(f'{self.chat_prefix}Map order: ')
		for index, (uid, _) in enumerate(self.match_maps, start=1):
			map_name = (await Map.get_by_uid(uid)).name
			await self.instance.chat(f'{self.chat_prefix}[{index}/{len(self.match_maps)}] {map_name}')

		await self.instance.map_manager.set_next_map(await Map.get_by_uid(self.match_maps[0][0]))
		await self.instance.gbx('NextMap')


	async def stop_match(self, player, *args, **kwargs):
		for signal, target in self.context.signals.listeners:
			if target == self.set_settings_next_map:
				signal.unregister(target)
		self.match_maps = self.brawl_maps
		self.match_players = []


	async def shuffle_maps(self):
		random.shuffle(self.match_maps)


	async def update_finish_timeout(self, timeout):
		settings = await self.instance.mode_manager.get_settings()
		settings['S_FinishTimeout'] = timeout
		await self.instance.mode_manager.update_settings(settings)


	async def set_settings_next_map(self, map):
		settings = await self.instance.mode_manager.get_settings()
		for index, (uid, timeout) in enumerate(self.match_maps):
			if uid == map.uid:
				if index == len(self.match_maps) - 1 and settings['S_WarmUpNb'] == 1:
					settings['S_WarmUpNb'] = 0
					await self.instance.mode_manager.update_settings(settings)
				await self.update_finish_timeout(timeout)
				await self.instance.map_manager.set_next_map(
					await Map.get_by_uid(
						self.match_maps[(index + 1) % len(self.match_maps)][0]
					)
				)

