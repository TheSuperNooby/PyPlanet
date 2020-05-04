from pyplanet.views.generics.list import ManualListView
from pyplanet.views.generics.alert import ask_input

class BrawlMapListView(ManualListView):
	title = 'Sentences for roulette'
	icon_style = 'Icons128x128_1'
	icon_substyle = 'Browse'

	async def get_fields(self):
		return [
			{
				'name': '#',
				'index': 'index',
				'sorting': True,
				'searching': False,
				'width': 10,
				'type': 'label'
			},
			{
				'name': 'Sentence',
				'index': 'sentence',
				'sorting': True,
				'searching': True,
				'search_strip_styles': True,
				'width': 90,
				'type': 'label',
				'action': self.action_edit
			}
		]

	def __init__(self, app, sentences):
		super().__init__()
		self.app = app
		self.sentences = sentences

	async def get_data(self):
		return [{'index': i, 'sentence': sentence} for (i, sentence) in zip(range(1,len(self.sentences)), self.sentences)]


	async def action_edit(self, player, values, sentence_info, **kwargs):
		new_sentence = await ask_input(player, 'Please enter the new sentence')
