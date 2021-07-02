import asyncio
import math
import logging
from operator import itemgetter

from xmlrpc.client import Fault
from pyplanet.apps.config import AppConfig
from pyplanet.apps.contrib.nightcup.views import TimerView, SettingsListView
from pyplanet.apps.contrib.nightcup.standings import StandingsLogicManager
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.apps.core.trackmania import callbacks as tm_signals
from pyplanet.apps.core.maniaplanet.models import Player
from pyplanet.contrib.command import Command
from pyplanet.core.ui.exceptions import UIPropertyDoesNotExist


async def format_time(seconds):
	return f'{seconds // 60}:{seconds % 60:02d}'


async def get_nr_kos(nr_players):
	return int((nr_players + 4) / 10) + 1


async def display(widget, player=None):
	try:
		if player:
			await widget.display(player)
		else:
			await widget.display()
	except AttributeError:
		pass


class NightCup(AppConfig):
	game_dependencies = ['trackmania']
	app_dependencies = ['core.maniaplanet', 'core.trackmania']

	TIME_UNTIL_NEXT_WALL = 3

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

		self.ta_finishers = []
		self.whitelisted = []
		self.ko_qualified = []

		self.settings_long = [
			{
				'name': 'nc_time_until_ta',
				'description': 'Time before TA phase starts',
				'type': int,
				'constraints': [(lambda x: x > 5 or x == 0 or x == -1,
								 'Time can not be shorter than 5 seconds.')],
				'default': '60',
				'value': 0
			},
			{
				'name': 'nc_ta_length',
				'description': 'Length of TA phase',
				'type': int,
				'constraints': [],
				'default': '2700',
				'value': 90000
			},
			{
				'name': 'nc_time_until_ko',
				'description': 'Time between TA phase and KO phase',
				'type': int,
				'constraints': [(lambda x: x > 5 or x == 0 or x == -1,
								 'Time can not be shorter than 5 seconds.')],
				'default': '600',
				'value': 0
			},
			{
				'name': 'nc_ta_wu_duration',
				'description': 'Length of warmups before TA for players to load the map',
				'type': int,
				'constraints': [],
				'default': '60',
				'value': 0
			},
			{
				'name': 'nc_ko_wu_duration',
				'description': 'Length of warmups before KO for players to load the map',
				'type': int,
				'constraints': [],
				'default': '60',
				'value': 0
			},
			{
				'name': 'nc_finish_timeout',
				'description': 'Timeout after first player finishes in KO phase',
				'type': int,
				'constraints': [],
				'default': '90',
				'value': 10
			},
			{
				'name': 'nc_qualified_percentage',
				'description': 'Percentage of TA finishers that will qualify to the KO phase',
				'type': int,
				'constraints': [(lambda x: 0 <= x <= 100, 'Percentage must be between 0 and 100')],
				'default': '50',
				'value': 50
			}
		]

		self.settings = {setting['name']: setting['value'] for setting in self.settings_long}
		self.chat_reset = '$z$fff$s'
		self.chat_prefix = f'$fffRPG $036NIGHTCUP $fff- {self.chat_reset}'

		self.admin = None

		self.nc_active = False
		self.ta_active = False
		self.ko_active = False
		self.ko_wu_enabled = False

		self.backup_script_name = None
		self.backup_settings = None
		self.backup_dedi_ui_params = {}
		self.backup_standings_apps = []

		self.open_views = []
		self.timer_view = None

		self.standings_logic_manager = StandingsLogicManager(self)

	async def on_init(self):
		await super().on_init()

	async def on_start(self):
		await self.instance.permission_manager.register(
			'nc_control',
			'Starting/Stopping nightcups',
			app=self,
			min_level=2
		)

		await self.instance.command_manager.register(
			Command(
				'start',
				namespace='nc',
				target=self.start_nc,
				perms='nightcup:nc_control',
				admin=True
			),
			Command(
				'stop',
				namespace='nc',
				target=self.stop_nc,
				perms='nightcup:nc_control',
				admin=True
			),
			Command(
				'settings',
				namespace='nc',
				target=self.nc_settings,
				perms='nightcup:nc_control',
				admin=True
			),
			Command(
				'addqualified',
				namespace='nc',
				aliases=['aq'],
				target=self.add_qualified,
				perms='nightcup:nc_control',
				admin=True
			).add_param(
				'player',
				nargs='*',
				type=str,
				required=True
			),
			Command(
				'removequalified',
				namespace='nc',
				aliases=['rq'],
				target=self.remove_qualified,
				perms='nightcup:nc_control',
				admin=True
			).add_param(
				'player',
				nargs='*',
				type=str,
				required=True
			),
			Command(
				'chat',
				namespace='nc',
				target=self.nc_chat_command,
				perms='nightcup:nc_control',
				admin=True
			).add_param(
				'message',
				nargs='*',
				type=str,
				required=True
			),
			Command(
				'whitelist',
				namespace='nc',
				aliases=['wl'],
				target=self.whitelist,
				perms='nightcup:nc_control',
				admin=True
			).add_param(
				'players',
				nargs='*',
				type=str,
				required=True
			),
			Command(
				'unwhitelist',
				namespace='nc',
				aliases=['unwl'],
				target=self.unwhitelist,
				perms='nightcup:nc_control',
				admin=True
			).add_param(
				'players',
				nargs='*',
				type=str,
				required=True
			),
			Command(
				'removestanding',
				namespace='nc',
				target=self.standings_logic_manager.remove_from_currentcps,
				perms='nightcup:nc_control',
				admin=True
			).add_param(
				'players',
				nargs='*',
				type=str,
				required=True
			)
		)

	async def nc_chat_command(self, player, data, **kwargs):
		await self.nc_chat(' '.join(data.message))

	async def start_nc(self, player, *args, **kwargs):
		if self.nc_active:
			await self.nc_chat(f'A nightcup is currently in progress!', player)
		else:
			await self.nc_chat(f'Nightcup is starting now!')
			await self.nc_chat(f'Set whitelisted players now using //nc wl player1 player2 player3', player)
			self.admin = player
			await self.set_ui_elements()

			self.nc_active = True
			await self.backup_mode_settings()
			await asyncio.sleep(self.TIME_UNTIL_NEXT_WALL)

			await self.wait_for_ta_start()

	async def backup_mode_settings(self):
		self.backup_script_name = await self.instance.mode_manager.get_current_full_script()
		self.backup_settings = await self.instance.mode_manager.get_settings()

	async def set_ta_settings(self):
		await self.instance.mode_manager.set_next_script('TimeAttack.Script.txt')

		await self.restart_map()
		while await self.instance.mode_manager.get_current_full_script() != 'TimeAttack.Script.txt':
			await asyncio.sleep(1)
		await self.set_ta_modesettings()

	async def set_ta_modesettings(self):
		settings = await self.instance.mode_manager.get_settings()

		settings['S_TimeLimit'] = self.settings['nc_ta_length']
		if self.settings['nc_ta_wu_duration'] == -1 or self.settings['nc_ta_wu_duration'] == 0:
			settings['S_WarmUpNb'] = -1
			await self.nc_chat(f'Live with TA now!')
		else:
			settings['S_WarmUpNb'] = 1
			settings['S_WarmUpDuration'] = self.settings['nc_ta_wu_duration']
			await self.nc_chat(
				f"Warmup of {await format_time(self.settings['nc_ta_wu_duration'])} for people to load the map.")
			await self.nc_chat(f'Live with TA after WarmUp!')
		await self.update_modesettings(settings)

	async def whitelist(self, player, data, **kwargs):
		for p in data.players:
			if p in self.whitelisted:
				await self.nc_chat(f'$i$f00Player is already whitelisted')
				continue
			self.whitelisted.append(p)
			await self.nc_chat(f'Added login {p} to the whitelist')

	async def unwhitelist(self, player, data, **kwargs):
		for p in data.players:
			if p not in self.whitelisted:
				await self.nc_chat(f'$i$f00Player was not whitelisted')
				continue
			self.whitelisted.remove(p)
			await self.nc_chat(f'Removed login {p} from the whitelist')

	async def wait_for_ta_start(self):
		if not (self.settings['nc_time_until_ta'] == -1 or self.settings['nc_time_until_ta'] == 0):
			self.timer_view = TimerView(self)
			self.open_views.append(self.timer_view)
			self.timer_view.title = f"TA phase starts in {await format_time(self.settings['nc_time_until_ta'])}"
			for player in self.instance.player_manager.online:
				await display(self.timer_view, player)

			secs = 0
			while self.settings['nc_time_until_ta'] - secs > 0 and self.timer_view:
				self.timer_view.title = f"TA phase starts in {await format_time(self.settings['nc_time_until_ta'] - secs)}"
				for player in self.instance.player_manager.online:
					await display(self.timer_view, player)
				await asyncio.sleep(1)
				secs += 1

			if self.timer_view:
				await self.timer_view.destroy()
				self.timer_view = None

		await asyncio.sleep(1)

		if not self.nc_active:
			return

		await self.set_ta_settings()
		self.ta_active = True
		await self.standings_logic_manager.start()
		await self.standings_logic_manager.set_standings_widget_title('TA Phase')
		await self.standings_logic_manager.set_ta_listeners()
		self.context.signals.listen(mp_signals.flow.round_end, self.get_qualified)
		self.context.signals.listen(mp_signals.flow.round_end, self.wait_for_ko_start)

	async def wait_for_ko_start(self, count=0, time=0):
		await asyncio.sleep(1)
		if not self.nc_active:
			return
		self.ta_active = False

		await self.standings_logic_manager.extended_view.destroy()
		self.standings_logic_manager.extended_view = None

		await self.standings_logic_manager.set_standings_widget_title('Current CPs')
		await self.standings_logic_manager.set_ko_listeners()
		settings = await self.instance.mode_manager.get_settings()
		settings['S_TimeLimit'] = -1
		settings['S_WarmUpDuration'] = 0
		settings['S_WarmUpNb'] = -1
		await self.update_modesettings(settings)

		await self.unregister_signals([self.wait_for_ko_start])

		await self.restart_map()
		if not (self.settings['nc_time_until_ko'] == -1 or self.settings['nc_time_until_ko'] == 0):
			self.timer_view = TimerView(self)
			self.open_views.append(self.timer_view)
			self.timer_view.title = f"KO phase starts in {await format_time(self.settings['nc_time_until_ko'])}"
			for player in self.instance.player_manager.online:
				await display(self.timer_view, player)

			secs = 0
			while self.settings['nc_time_until_ko'] - secs > 0 and self.timer_view:
				self.timer_view.title = f"KO phase starts in {await format_time(self.settings['nc_time_until_ko'] - secs)}"
				for player in self.instance.player_manager.online:
					await display(self.timer_view, player)
				await asyncio.sleep(1)
				secs += 1

			if self.timer_view:
				await self.timer_view.destroy()
				self.timer_view = None

		await asyncio.sleep(1)

		if not self.nc_active:
			return

		self.context.signals.listen(mp_signals.map.map_begin, self.set_ko_settings)

		await self.instance.map_manager.set_next_map(self.instance.map_manager.current_map)
		self.ko_active = True
		await self.standings_logic_manager.set_standings_widget_title('KO phase')
		try:
			await self.instance.gbx('NextMap')
		except Fault as e:
			await self.nc_chat('$f00Something went wrong while skipping the map', self.admin)
			await self.nc_chat(str(e), self.admin)

	async def stop_nc(self, player, *args, **kwargs):
		if not self.nc_active:
			await self.nc_chat(f'No nightcup is currently in progress!', player)
			return
		await self.nc_chat(f'Admin {player.nickname}{self.chat_reset} stopped nightcup!')
		await self.reset_server()

	async def reset_server(self):
		self.nc_active = False

		await self.unregister_signals(
			[self.get_qualified, self.wait_for_ko_start, self.set_ko_settings,
			 self.knockout_players, self.display_nr_of_kos, self.display_ko_wu_info]
		)
		self.ta_active = False
		self.ko_active = False
		await self.standings_logic_manager.stop()
		self.admin = None

		for view in self.open_views:
			await view.destroy()
		self.open_views.clear()
		self.timer_view = None

		self.ta_finishers.clear()
		self.whitelisted.clear()
		self.ko_qualified.clear()

		await self.reset_backup()
		await self.reset_ui_elements()

	async def reset_backup(self):
		if not (self.backup_script_name and self.backup_settings):
			return

		await asyncio.sleep(5)
		await self.instance.mode_manager.set_next_script(self.backup_script_name)
		await self.instance.mode_manager.update_next_settings(self.backup_settings)
		await self.restart_map()

	async def set_ko_settings(self, map):
		await self.unregister_signals([self.set_ko_settings])

		await self.instance.mode_manager.set_next_script('Rounds.Script.txt')

		await self.restart_map()
		while await self.instance.mode_manager.get_current_full_script() != 'Rounds.Script.txt':
			await asyncio.sleep(1)
		await self.set_ko_modesettings()

		self.context.signals.listen(mp_signals.flow.round_end, self.knockout_players)
		self.context.signals.listen(mp_signals.flow.round_start, self.display_nr_of_kos)

	async def set_ko_modesettings(self):
		settings = await self.instance.mode_manager.get_settings()

		settings['S_PointsLimit'] = -1
		settings['S_RoundsPerMap'] = -1
		settings['S_PointsRepartition'] = ','.join(str(x) for x in range(len(self.ko_qualified), 0, -1))
		settings['S_FinishTimeout'] = self.settings['nc_finish_timeout']

		self.ko_wu_enabled = not (self.settings['nc_ko_wu_duration'] == -1 or self.settings['nc_ko_wu_duration'] == 0)
		if self.ko_wu_enabled:
			settings['S_WarmUpNb'] = 1
			settings['S_WarmUpDuration'] = self.settings['nc_ko_wu_duration']
		else:
			settings['S_WarmUpNb'] = -1

		self.context.signals.listen(tm_signals.warmup_start, self.display_ko_wu_info)

		await self.update_modesettings(settings)

	async def display_ko_wu_info(self):
		await self.unregister_signals([self.display_ko_wu_info])
		if self.ko_wu_enabled:
			await self.nc_chat(
				f"Warmup of {await format_time(self.settings['nc_ko_wu_duration'])} for people to load the map.")
			await self.nc_chat(f'Live with KO after WarmUp!')
		else:
			await self.nc_chat(f'Live with KO now!')

	async def get_qualified(self, count, time):
		await self.unregister_signals([self.get_qualified])

		self.ko_qualified = self.whitelisted + [p['login'] for (i, p) in enumerate(self.ta_finishers)
							 if i * 100 < round(len(self.ta_finishers) * self.settings['nc_qualified_percentage'], 1)]
		try:
			for p in self.instance.player_manager.online_logins:
				if p in self.ko_qualified:
					await self.nc_chat('Well done, you qualified for the KO phase!', p)

					await self.instance.gbx('ForceSpectator', p, 2)
				elif p in [p['login'] for p in self.ta_finishers]:
					await self.nc_chat('Unlucky, you did not qualify for the KO phase!', p)
					await self.force_spec_or_kick(p)
				else:
					await self.force_spec_or_kick(p)
		except Fault as e:
			pass

		if len(self.ko_qualified) == 0:
			await self.nc_chat('Noone finished TA Phase, stopping NightCup')
			await self.reset_server()
		elif len(self.ko_qualified) == 1:
			await self.finish_nightcup(self.ko_qualified[0])

	async def knockout_players(self, count, time):
		round_scores = (await self.instance.gbx('Trackmania.GetScores'))['players']
		nr_kos = await get_nr_kos(len(self.ko_qualified))
		round_scores = [(record['login'], record['prevracetime']) for record in round_scores if
						record['login'] in self.ko_qualified]

		round_scores.sort(key=itemgetter(1))
		round_scores = [p for p in round_scores if p[1] != -1]
		if len(round_scores) == 0:
			return

		round_logins = [p[0] for p in round_scores]

		if len(self.ko_qualified) <= 2 or len(round_scores) == 1:
			await self.finish_nightcup(round_scores[0][0])
			return

		dnfs = [p for p in self.ko_qualified if p not in round_logins]
		kos = round_logins[len(self.ko_qualified) - nr_kos:]
		qualified = round_logins[:len(self.ko_qualified) - nr_kos]

		self.ko_qualified = [p for p in self.ko_qualified if p in qualified]

		try:
			for i, p in enumerate(kos, start=1):
				await self.nc_chat(
					f'You have been eliminated from this KO: position {len(qualified) + i}/{len(self.ko_qualified) + nr_kos}', p)
				await self.force_spec_or_kick(p)
			for p in dnfs:
				await self.nc_chat(f'You have been eliminated from this KO: position DNF/{len(self.ko_qualified) + nr_kos}', p)
				await self.force_spec_or_kick(p)
			for i, p in enumerate(qualified, start=1):
				await self.nc_chat(f'You are still in! position {i}/{len(self.ko_qualified) + nr_kos}', p)
				await self.instance.gbx('ForceSpectator', p, 2)
		except Fault as e:
			pass

		kos.extend(dnfs)
		kos = [(await Player.get_by_login(login)).nickname for login in kos]
		kos_string = f'{self.chat_reset}, '.join(kos)
		await self.nc_chat(f'Players knocked out: {kos_string}')

	async def finish_nightcup(self, winner):
		await self.nc_chat(
			f'Player {(await Player.get_by_login(winner)).nickname}{self.chat_reset} wins this RPG NightCup, well played!')
		await self.reset_server()

	async def force_spec_or_kick(self, p):
		if self.instance.player_manager.count_spectators < self.instance.player_manager.max_spectators:
			await self.instance.gbx('ForceSpectator', p, 3)
		else:
			await self.instance.gbx('Kick', p)

	async def display_nr_of_kos(self, count, time):
		await self.nc_chat(
			f'{len(self.ko_qualified)} players left, number of KOs: {await get_nr_kos(len(self.ko_qualified))}')

	async def nc_chat(self, message, player=None):
		if player:
			await self.instance.chat(f'{self.chat_prefix}{message}', player)
		else:
			await self.instance.chat(f'{self.chat_prefix}{message}')

	async def nc_settings(self, player, *args, **kwargs):
		settings_view = SettingsListView(self, player)
		await settings_view.display(player=player)

	async def get_long_settings(self):
		return self.settings_long

	async def update_settings(self, new_settings):
		self.settings = new_settings
		for key in new_settings:
			for setting_long in self.settings_long:
				if setting_long['name'] == key:
					setting_long['value'] = new_settings[key]

	async def add_qualified(self, player, data, **kwargs):
		if not self.nc_active:
			await self.nc_chat('$i$f00No nightcup is currently active', player)
			return
		for player_to_add in data.player:
			if not player_to_add in self.instance.player_manager.online_logins:
				await self.nc_chat('$i$f00Player is currently not on the server', player)
				continue
			if player_to_add in self.ko_qualified:
				await self.nc_chat(f'$i$f00Player is already in the qualified list')
				continue
			self.ko_qualified.append(player_to_add)
			await self.nc_chat(f'Player {(await Player.get_by_login(player_to_add)).nickname} {self.chat_reset} has been added to the '
							   f'qualified list')

	async def remove_qualified(self, player, data, **kwargs):
		if not self.nc_active:
			await self.nc_chat('$i$f00No nightcup is currently active', player)
			return
		players_to_remove = data.player
		for player_to_remove in players_to_remove:
			if not player_to_remove in self.ko_qualified:
				await self.nc_chat('$i$f00Player is currently not in the qualified list', player)
				continue
			self.ko_qualified.remove(player_to_remove)
			await self.nc_chat(f'Player {(await Player.get_by_login(player_to_remove)).nickname} {self.chat_reset}'
							   f'has been removed from the qualified list')

	async def set_ui_elements(self):
		await self.set_properties()
		await self.disable_standings_uis()
		self.context.signals.listen(mp_signals.map.map_begin, self.disable_standings_uis)
		await self.move_dedi_ui()

	async def set_properties(self):
		try:
			await self.instance.ui_manager.app_managers['core.pyplanet'].manialinks['pyplanet__controller'].hide()
		except (UIPropertyDoesNotExist, KeyError):
			logging.error('Something went wrong while moving the pyplanet logo.')
		try:
			await self.instance.ui_manager.app_managers['clock'].manialinks['pyplanet__widgets_clock'].hide()
		except (UIPropertyDoesNotExist, KeyError):
			logging.error('Something went wrong while moving the pyplanet clock.')

		await self.move_properties(-20)

	async def move_dedi_ui(self):
		for app in self.instance.ui_manager.app_managers.values():
			dedi_view = app.manialinks.get('pyplanet__widgets_dedimaniarecords')
			if dedi_view:
				self.backup_dedi_ui_params = {
					'top_entries': dedi_view.top_entries,
					'record_amount': dedi_view.record_amount,
					'widget_x': dedi_view.widget_x,
					'widget_y': dedi_view.widget_y
				}
				dedi_view.top_entries = 1
				dedi_view.record_amount = 5
				dedi_view.widget_x = 125
				dedi_view.widget_y = 0

				await dedi_view.display()

	async def disable_standings_uis(self, map=None):
		self.backup_standings_apps = [app for app in ['live_rankings', 'currentcps'] if
									  app in self.instance.apps.apps and
									  app not in self.instance.apps.unloaded_apps]
		for label in self.backup_standings_apps:
			app = self.instance.apps.apps.pop(label)
			await app.on_stop()
			await app.on_destroy()
			self.instance.apps.unloaded_apps[label] = app.module.__name__
			del app

	async def reset_ui_elements(self):
		await self.reset_properties()
		await self.reset_dedi_ui()
		await self.unregister_signals([self.disable_standings_uis])
		await self.reset_standings_uis()

	async def reset_properties(self):
		try:
			await self.instance.ui_manager.app_managers['core.pyplanet'].manialinks['pyplanet__controller'].show()
		except (UIPropertyDoesNotExist, KeyError, AttributeError):
			logging.error('Something went wrong while moving the pyplanet logo.')
		try:
			await self.instance.ui_manager.app_managers['clock'].manialinks['pyplanet__widgets_clock'].show()
		except (UIPropertyDoesNotExist, KeyError, AttributeError):
			logging.error('Something went wrong while moving the pyplanet clock.')

		await self.move_properties(20)



	async def move_properties(self, offset):
		# This functionality is currently broken by an error in PyPlanet code
		# where requesting attributes is refused in all cases

		# properties = ['countdown', 'personal_best_and_rank', 'position']
		# for p in properties:
		# 	pos = [float(c) for c in self.instance.ui_manager.properties.get_attribute(p, 'pos').split()]
		# 	pos[1] += offset
		# 	pos = ' '.join([str(c) for c in pos])
		# 	self.instance.ui_manager.properties.set_attribute(p, 'pos', pos)

		# Working hardcode fix
		properties = {
			'countdown': [float(c) for c in '153. -7. 5.'.split()],
			'personal_best_and_rank': [float(c) for c in '157. -24. 5.'.split()],
			'position': [float(c) for c in '150.5 -28. 5.'.split()]
		}

		for k, v in properties.items():
			v[1] += offset
			self.instance.ui_manager.properties.set_attribute(k, 'pos', ' '.join(str(c) for c in v))

		# Update properties for every player
		await self.instance.ui_manager.properties.send_properties()

	async def reset_dedi_ui(self):
		for app in self.instance.ui_manager.app_managers.values():
			dedi_view = app.manialinks.get('pyplanet__widgets_dedimaniarecords')
			if dedi_view:
				dedi_view.top_entries = self.backup_dedi_ui_params['top_entries']
				dedi_view.record_amount = self.backup_dedi_ui_params['record_amount']
				dedi_view.widget_x = self.backup_dedi_ui_params['widget_x']
				dedi_view.widget_y = self.backup_dedi_ui_params['widget_y']

				await dedi_view.display()

	async def reset_standings_uis(self):
		for label in self.backup_standings_apps:
			if label in self.instance.apps.unloaded_apps:
				try:
					app = self.instance.apps.unloaded_apps[label]
					self.instance.apps.populate([app], in_order=True)
					if label not in self.instance.apps.apps:
						raise Exception()  # Flow control, stop executing restart of app.
					await self.instance.apps.apps[label].on_init()
					await self.instance.apps.apps[label].on_start()

					del self.instance.apps.unloaded_apps[label]
				except Exception as e:
					logging.error('Can\'t start app {}, Got exception with error: {}'.format(label, str(e)))
					pass

	async def unregister_signals(self, targets):
		for signal, target in self.context.signals.listeners:
			if target in targets:
				signal.unregister(target)

	async def get_nr_qualified(self):
		if self.ta_active:
			return math.ceil(round(len(self.ta_finishers) / 100 * self.settings['nc_qualified_percentage'], 1))
		if self.ko_active:
			return len(self.ko_qualified) - await get_nr_kos(len(self.ko_qualified))
		return -1

	async def spec_player(self, player, target_login):
		await self.instance.gbx.multicall(
			self.instance.gbx('ForceSpectator', player.login, 3),
			self.instance.gbx('ForceSpectatorTarget', player.login, target_login, -1)
		)

	async def update_modesettings(self, settings):
		try:
			await self.instance.mode_manager.update_settings(settings)
		except Exception as e:
			await self.nc_chat('$f00Couldn\'t set the modesettings, please check if all are set correctly!',
									 self.admin)
			await self.nc_chat(str(e), self.admin)

	async def restart_map(self):
		try:
			await self.instance.gbx('RestartMap')
		except Fault as e:
			await self.nc_chat('$f00Something went wrong while restarting the map', self.admin)
			await self.nc_chat(str(e), self.admin)

