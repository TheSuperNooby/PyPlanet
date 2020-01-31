from pyplanet.views.generics.list import ManualListView


class AdminPmLogView(ManualListView):
	title = 'Admin PM log'
	icon_style = 'Icons128x128_1'
	icon_substyle = 'Statistics'
	items = 'messages'

	def __init__(self, app, pm_log):
		super().__init__(self)
		self.app = app
		self.manager = app.context.ui
		self.provide_search = False

		self.pm_log = pm_log

	async def get_fields(self):
		return [
			{
				'name': 'Nickname',
				'index': 'nickname',
				'sorting': False,
				'searching': False,
				'width': 40,
				'type': 'label'
			},
			{
				'name': 'Message',
				'index': 'message',
				'sorting': False,
				'searching': False,
				'width': 70,
				'type': 'label'
			}

			]

	async def get_data(self):
		messages = []
		for message in self.pm_log:
			messages.append(
				{
					'nickname': message[0].nickname,
					'message': message[1]
				}
			)

		return messages
