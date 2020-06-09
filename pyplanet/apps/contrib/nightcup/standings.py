import collections

from pyplanet.apps.contrib.nightcup.views import NcStandingsWidget
from pyplanet.apps.core.trackmania import callbacks as tm_signals
from pyplanet.apps.core.maniaplanet import callbacks as mp_signals
from pyplanet.core.ui.exceptions import UIPropertyDoesNotExist



class StandingsLogicManager:

	def __init__(self, app):
		self.app = app

		self.current_rankings = []
		self.last_qualified_cps = []
		self.app.ta_finishers = self.current_rankings

		self.current_cps = {}
		self.standings_widget = None
		self.player_cps = []

		self.backup_ui_attributes = None

		self.listeners = {
			mp_signals.map.map_start: self.empty_data,
			tm_signals.finish: self.player_finish,
			mp_signals.player.player_connect: self.player_connect,
		}

		self.ko_listeners = {
			tm_signals.waypoint: self.player_cp,
			tm_signals.start_line: self.player_start,
			mp_signals.player.player_disconnect: self.player_leave_play,
			mp_signals.player.player_enter_spectator_slot: self.player_leave_play
		}

	async def start(self):
		for callback, listener in self.listeners.items():
			self.app.context.signals.listen(callback, listener)
		await self.set_ko_listeners()

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
				time_at_cp = raw['racetime']
				last_qualified_time_at_cp = self.last_qualified_cps[raw['checkpointinrace']]
				current_ranking['split'] = time_at_cp - last_qualified_time_at_cp

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
		if self.app.ko_active and player.login not in self.current_cps:
			self.current_cps[player.login] = PlayerCP(player)
			await self.update_standings_widget()

	# When a player passes the finish line
	async def player_finish(self, player, race_time, race_cps, is_end_race, raw, *args, **kwargs):
		if self.app.ta_active:
			current_ranking = next((x for x in self.current_rankings if x['login'] == player.login), None)
			if current_ranking:
				current_ranking['split'] = 0
				current_ranking['cp'] = -1
				if race_time < current_ranking['score']:
					current_ranking['score'] = race_time
					current_ranking['cps'] = race_cps
			else:
				new_ranking = dict(login=player.login, nickname=player.nickname, score=race_time, cp=-1,
								   split=0, cps=race_cps)
				self.current_rankings.append(new_ranking)

			self.current_rankings.sort(key=lambda x: x['score'])
			self.last_qualified_cps = self.current_rankings[(await self.app.get_nr_qualified()) - 1]['cps']

		else:
			# Create new PlayerCP object if there is no PlayerCP object for that player yet
			if player.login not in self.current_cps:
				self.current_cps[player.login] = PlayerCP(player)

			# Set the current CP to -1 (signals finished) when a player finishes the race
			if is_end_race:
				self.current_cps[player.login].cp = -1
			else:
				self.current_cps[player.login].cp = raw['checkpointinrace'] + 1  # Otherwise just update the current cp
			self.current_cps[player.login].time = race_time

		await self.update_standings_widget()

	# # When a player connects
	async def player_connect(self, player, *args, **kwargs):
		await self.update_standings_widget(player)

	# When a player enters spectator mode or disconnects
	async def player_leave_play(self, player, *args, **kwargs):
		if self.app.ta_active:
			current_ranking = next((x for x in self.current_rankings if x['login'] == player.login), None)
			if current_ranking:
				current_ranking['cp'] = '📷'
				current_ranking['split'] = 0
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
				cp = pcp.cp
				cpstr = str(cp)
				if cp == -1:
					cpstr = "fin"
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

class PlayerCP:
	def __init__(self, player, cp=0, time=0):
		self.player = player
		self.cp = cp
		self.time = time
		self.virt_qualified = False
		self.virt_eliminated = False

