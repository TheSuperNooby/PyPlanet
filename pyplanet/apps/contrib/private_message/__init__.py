import asyncio

from pyplanet.apps.config import AppConfig
from pyplanet.apps.contrib.private_message.views import AdminPmLogView
from pyplanet.contrib.command import Command
from pyplanet.contrib.player.exceptions import PlayerNotFound


class PrivateMessage(AppConfig):
	game_dependencies = ['trackmania']
	app_dependencies = ['core.maniaplanet', 'core.trackmania']
	admin_pm_log = []

	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)

	async def on_init(self):
		await super().on_init()

	async def on_start(self):
		await self.instance.permission_manager.register(
			'admin_pm',
			'Private message for admins',
			app=self,
			min_level=2
		)

		await self.instance.permission_manager.register(
			'pm_log',
			'Private message log for admins',
			app=self,
			min_level=2
		)

		await self.instance.command_manager.register(
			Command(
				'pm',
				target=self.command_pm
			).add_param(
				'player',
				required=True,
				type=str,
				help='Login to send private message to'
			).add_param('message', required=True, type=str, help='Message')
		)

		await self.instance.command_manager.register(
			Command(
				'adminpm',
				target=self.command_adminpm,
				perms='private_message:admin_pm',
				admin=True
			).add_param(
				'message',
				required=True,
				type=str,
				help='Message'
			)
		)

		await self.instance.command_manager.register(
			Command(
				'pmlog',
				target=self.command_pm_log,
				perms='private_message:pm_log',
				admin=True
			)
		)

	async def on_stop(self):
		await super().on_stop()

	async def on_destroy(self):
		await super().on_destroy()


	async def append_pm_log(self, player, raw_message):
		if len(self.admin_pm_log) > 100:
			self.admin_pm_log.pop(0)

		self.admin_pm_log.append((player, raw_message))

	async def command_pm(self, player, data, *args, **kwargs):
		try:
			to_player = await self.instance.player_manager.get_player(data.player)
			message = '$ff0[$f00pm$ff0] [{}$z$i$ff0 -> {}$z$i$ff0] {}'.format(player.nickname, to_player.nickname, ' '.join(kwargs['raw'][1:]))

			await self.instance.gbx.multicall(
				self.instance.chat(message, data.player),
				self.instance.chat(message, player)
			)
		except PlayerNotFound:
			message = '$i$f00Unknown login!'
			await self.instance.chat(message, player)


	async def command_adminpm(self, player, data, *args, **kwargs):
		online_players = self.instance.player_manager.online
		raw_message = ' '.join(kwargs['raw'])
		message = '$ff0[$f00pm$ff0] [{}$z$i$ff0 -> Admins] {}'.format(player.nickname, raw_message)
		for online_player in online_players:
			if online_player.get_level_string() == 'Admin' or online_player.get_level_string() == 'MasterAdmin':
				await self.instance.chat(message, online_player)

		await self.append_pm_log(player, raw_message)

	async def command_pm_log(self, player, data, *args, **kwargs):

		view = AdminPmLogView(self, self.admin_pm_log)
		await view.display(player=player.login)
		return view
