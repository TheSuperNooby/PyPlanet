import collections

from pyplanet.apps.contrib.nightcup.views import NcStandingsWidget, ExtendButtonView
from pyplanet.apps.core.trackmania import callbacks as tm_signals
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.core.ui.exceptions import UIPropertyDoesNotExist



class StandingsLogicManager:

	def __init__(self, app):
		self.app = app

		self.current_rankings = []
		self.last_qualified_cps = []
		self.app.ta_finishers = []

		self.current_cps = {}
		self.standings_widget = None
		self.player_cps = []

		self.backup_ui_attributes = None

		self.extended_data = {}
		self.extended_view = None

		self.listeners = {
			mp_signals.map.map_start: self.empty_data,
			tm_signals.finish: self.player_finish,
			mp_signals.player.player_connect: self.player_connect,
			tm_signals.start_line: self.player_start
		}

		self.ko_listeners = {
			tm_signals.waypoint: self.player_cp,
			mp_signals.player.player_disconnect: self.player_leave_play,
			mp_signals.player.player_enter_spectator_slot: self.player_leave_play
		}

	async def start(self):
		await self.set_ko_listeners()

		for callback, listener in self.listeners.items():
			self.app.context.signals.listen(callback, listener)

		self.extended_view = ExtendButtonView(self.app, self)
		for player in self.app.instance.player_manager.online:
			self.extended_data[player.login] = dict(play=False, spec=True)
			spec = bool((await self.app.instance.gbx('GetPlayerInfo', player.login))['SpectatorStatus'])
			await self.update_extended_widget(player, spec)

		# Make sure we move the rounds_scores and other gui elements.
		try:
			self.backup_ui_attributes = {
				'round_scores': self.app.instance.ui_manager.properties.get_attribute('round_scores', 'pos'),
				'multilap_info': self.app.instance.ui_manager.properties.get_attribute('multilap_info', 'pos')
			}
		except UIPropertyDoesNotExist:
			pass
		self.app.instance.ui_manager.properties.set_attribute('round_scores', 'pos', '-126.5 87. 150.')
		self.app.instance.ui_manager.properties.set_attribute('multilap_info', 'pos', '107., 88., 5.')


		self.standings_widget = NcStandingsWidget(self.app, self)
		await self.standings_widget.display()

	async def stop(self):
		await self.app.unregister_signals(list(self.listeners.values()) + list(self.ko_listeners.values()))
		self.current_rankings.clear()
		self.last_qualified_cps.clear()
		self.current_cps.clear()
		self.player_cps.clear()
		if self.backup_ui_attributes:
			for att, value in self.backup_ui_attributes.items():
				self.app.instance.ui_manager.properties.set_attribute(att, 'pos', value)
		if self.standings_widget:
			await self.standings_widget.destroy()
			self.standings_widget = None

	async def set_standings_widget_title(self, title):
		if self.standings_widget:
			self.standings_widget.title = title

	# When a player passes a CP
	async def player_cp(self, player, race_time, raw, *args, **kwargs):
		if self.app.ta_active:
			current_ranking = next((x for x in self.current_rankings if x['login'] == player.login), None)
			if current_ranking:
				current_ranking['cp'] = raw['checkpointinrace'] + 1
				if self.last_qualified_cps:
					last_qualified_time_at_cp = self.last_qualified_cps[raw['checkpointinrace']]
					current_ranking['split'] = race_time - last_qualified_time_at_cp
					self.current_rankings.sort(key=lambda x: (x['score'] == -1, x['score'], x['cp'] == 0, x['split']))

		if self.app.ko_active:
			cp = raw['checkpointinrace']  # Have to use raw to get the current CP
			# Create new PlayerCP object if there is no PlayerCP object for that player yet
			if player.login not in self.current_cps:
				self.current_cps[player.login] = PlayerCP(player)
			self.current_cps[player.login].cp = cp + 1  # +1 because checkpointinrace starts at 0
			self.current_cps[player.login].time = race_time
		await self.update_standings_widget()

	# When a player starts the race
	async def player_start(self, player, *args, **kwargs):
		if self.app.ta_active:
			await self.update_extended_widget(player, False)

		if self.app.ta_active and not next((x for x in self.current_rankings if x['login'] == player.login), None):
			new_ranking = dict(login=player.login, nickname=player.nickname, score=-1, cp=0,
							   split=0, cps=None)
			self.current_rankings.append(new_ranking)

		if self.app.ko_active and player.login not in self.current_cps:
			self.current_cps[player.login] = PlayerCP(player)

		await self.update_standings_widget()

	# When a player passes the finish line
	async def player_finish(self, player, race_time, race_cps, is_end_race, raw, *args, **kwargs):
		if self.app.ta_active:
			current_ranking = next((x for x in self.current_rankings if x['login'] == player.login), None)
			if not next((x for x in self.app.ta_finishers if x['login'] == player.login), None):
				self.app.ta_finishers.append(current_ranking)
			if current_ranking:
				if self.last_qualified_cps:
					last_qualified_time_at_cp = self.last_qualified_cps[raw['checkpointinrace']]
					current_ranking['split'] = race_time - last_qualified_time_at_cp
				else:
					current_ranking['split'] = 0
				current_ranking['cp'] = -1
				if current_ranking['score'] == -1 or race_time < current_ranking['score']:
					current_ranking['score'] = race_time
					current_ranking['cps'] = race_cps
			else:
				new_ranking = dict(login=player.login, nickname=player.nickname, score=race_time, cp=-1,
								   split=0, cps=race_cps)
				self.current_rankings.append(new_ranking)
				self.app.ta_finishers.append(new_ranking)

			self.current_rankings.sort(key=lambda x: (x['score'] == -1, x['score'], x['split']))
			self.app.ta_finishers.sort(key=lambda x: x['score'])
			self.last_qualified_cps = self.current_rankings[(await self.app.get_nr_qualified()) - 1]['cps']

		else:
			# Create new PlayerCP object if there is no PlayerCP object for that player yet
			if player.login not in self.current_cps:
				self.current_cps[player.login] = PlayerCP(player)
			self.current_cps[player.login].time = race_time

		await self.update_standings_widget()

	# When a player connects
	async def player_connect(self, player, *args, **kwargs):
		self.extended_data[player.login] = dict(play=False, spec=True)
		spec = bool((await self.app.instance.gbx('GetPlayerInfo', player.login))['SpectatorStatus'])
		await self.update_extended_widget(player, spec)
		await self.update_standings_widget(player)

	# When a player enters spectator mode or disconnects
	async def player_leave_play(self, player, *args, **kwargs):
		if player and self.app.ta_active:
			await self.update_extended_widget(player, True)

		if self.app.ta_active:
			current_ranking = next((x for x in self.current_rankings if x['login'] == player.login), None)
			if current_ranking['score'] != -1:
				current_ranking['cp'] = '📷'
				current_ranking['split'] = 0
			else:
				self.current_rankings.remove(current_ranking)
			await self.update_standings_widget()

		# Remove the current CP from the widget only when the player is already out and goes into spec/leaves the server
		if self.app.ko_active:
			virt_qualified = [player for player in self.current_cps if player in self.app.ko_qualified]
			if player.login not in virt_qualified or virt_qualified.index(player.login) >= await self.app.get_nr_qualified():
				self.current_cps.pop(player.login, None)
				await self.update_standings_widget()

	# When the map ends
	async def empty_data(self, *args, **kwargs):
		self.current_rankings.clear()
		self.current_cps.clear()
		await self.update_standings_widget()

	# Update the view for all players
	async def update_standings_widget(self, player=None):
		if self.app.ko_active:
			# Used for sorting the PlayerCP objects by the 1. CP and 2. the time (Finished players are always on top)
			def keyfunc(key):
				lpcp = self.current_cps[key]
				return 1 if lpcp.cp == -1 else 2, -lpcp.cp, lpcp.time

			self.player_cps.clear()

			# Sort the PlayerCP objects by using the key function above and copy them into the player_cps-list
			for login in sorted(self.current_cps, key=lambda x: keyfunc(x)):
				pcp = self.current_cps[login]
				self.player_cps.append(pcp)

		# If standings_widget got destroyed already, displaying it will raise an AttributeError.
		# This problem usually occurs when nightcup is stopped while the widget is receiving updates
		try:
			if player:
				await self.standings_widget.display(player)  # Update the widget for all players
			else:
				await self.standings_widget.display()
		except AttributeError:
			pass

	async def spec_player(self, player, target_login):
		await self.app.instance.gbx.multicall(
			self.app.instance.gbx('ForceSpectator', player.login, 3),
			self.app.instance.gbx('ForceSpectatorTarget', player.login, target_login, -1)
		)

	async def set_ta_listeners(self):
		await self.app.unregister_signals(self.ko_listeners)

	async def set_ko_listeners(self):
		for callback, listener in self.ko_listeners.items():
			self.app.context.signals.listen(callback, listener)

	async def toggle_extended(self, player):
		if not self.app.ta_active:
			return
		extended = self.extended_data[player.login]
		if (await self.app.instance.gbx('GetPlayerInfo', player.login))['SpectatorStatus']:
			extended['spec'] = not extended['spec']
			await self.update_extended_widget(player, True)
		else:
			extended['play'] = not extended['play']
			await self.update_extended_widget(player, False)
		await self.standings_widget.display(player)

	async def update_extended_widget(self, player, spec):
		if spec:
			await self.extended_view.update_title(self.extended_data[player.login]['spec'])
		else:
			await self.extended_view.update_title(self.extended_data[player.login]['play'])

		try:
			await self.extended_view.display(player)
		except AttributeError:
			pass



class PlayerCP:
	def __init__(self, player, cp=0, time=0):
		self.player = player
		self.cp = cp
		self.time = time
		self.virt_qualified = False
		self.virt_eliminated = False

