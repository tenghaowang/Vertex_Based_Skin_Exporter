'''
Vertex Based Skin Weight IO
Author: Ryan Wang
Email: tenghaow@andrew.cmu.edu
'''

import maya.OpenMaya as OpenMaya
import cPickle as cPickle
import maya.cmds as cmds
import maya.OpenMayaAnim as OpenMayaAnim
import maya.OpenMayaUI as OpenMayaUI
from functools import partial


def getShape(node):
	#default consider only one shape node under transform node 
	#do not consider intermediateObject
	if cmds.nodeType(node) == 'transform':
		#remove intermediateObject
		shapes = cmds.listRelatives(node, c=True, s=True, ni=True, pa=True)
		if not shapes:
			shapes = []
		if len(shapes) > 0:
			return shapes[0]
	elif cmds.nodeType(node) in ['mesh', 'nurbsCurve', 'nurbsSurface']:
		return node
	return None


class SkinCluster(object):
	#define class variables
	kFileExtension = '.weight'
	
	@classmethod
	def exportData(cls, shape = None, filePath = None):
		skin = SkinCluster(shape)
		skin.exportSkin(filePath)
	
	@classmethod
	def importData(cls, shape=None, filePath = None):
		if not shape:
			try:
				shape = cmds.ls(sl=True)[0]
			except:
				raise RuntimeError('No shape is selected')
		#error proof for shape node		
		shape = getShape(shape)
		if not shape:
			raise RuntimeError('No shape connected to %s' % shape)
		if filePath == None:
			startDir = cmds.workspace(q = True, rd = True)
			filePath = cmds.fileDialog2(ds = 2, fm =1, dir = startDir, 
										okc='import',cap = 'Import Skin Data',ff = 'skin Files(*%s)' %SkinCluster.kFileExtension)

			if not filePath:
				return
			if not isinstance(filePath, basestring):
				filePath = filePath[0]

			#read data
			fh = open(filePath, 'rb')
			data = cPickle.load(fh)
			fh.close()
			#make sure the vertex count is the same
			#poly evaluate do not need to query the shape node
			numVertex = cmds.polyEvaluate(shape,v=True)
			importedVertex = len(data['blendWeights'])
			if numVertex != importedVertex:
				raise RuntimeError('Vertex counts do not match Selected mesh:) %d, Imported mesh %d' %(numVertex, importedVertex))

			#conmpare influencers from imported data and exsiting data
			#remove namespace and possible for skin weight retargetting
			influenceObjects = data['weights'].keys()
			#check all the influenceObjects exsits:
			unUsedInfluenceObjects =[]
			noMatchJoints=[]
			for joint in cmds.ls(type='joint'):
				noMatchJoints.append(SkinCluster.removeNameSpace(joint))
			for joint in influenceObjects:
				if joint in noMatchJoints:
					noMatchJoints.remove(joint)
				else:
					unUsedInfluenceObjects.append(joint)

			#if there were unmapped influences ask the user to map
			if unUsedInfluenceObjects and noMatchJoints:
				mappingDialog = MainSkinUI()
				mappingDialog.showModalDialog(noMatchJoints,unUsedInfluenceObjects)
				#mappingDialog.setInfluenceDialog(noMatchJoints, unUsedInfluenceObjects)
				for src, dst in mappingDialog.InfluenceMapping.items():
					data['weights'][dst] = data['weights'][src]
					del data['weights'][src]

			if SkinCluster.getSkinCluster(shape):
				skinCluster = SkinCluster(shape)
			else:
				#create a new skinCluster
				influenceObjects = data['weights'].keys()
				skinCluster = cmds.skinCluster(influenceObjects, shape, tsb=True, nw=2, n=data['name'])
				skinCluster = SkinCluster(shape)
			skinCluster.setData(data)
			print 'Data Imported'

	@classmethod
	def removeNameSpace(cls, nameStr):
		#nameSpace:Joint01 ->remove nameSpace
        #add functionality for remove nameSpace for situation below: 
        #s= 'nameSpace:joint1|nameSpace:joint2|nameSapce:joint3'
		tokens = nameStr.split('|')
		result = ''
		for i, token in enumerate(tokens):
			if i >0:
				result += '|'
			#get the last element
			result += token.split(':')[-1]
		return result

	#query the skinCluster attached to the given shape
	@classmethod
	def getSkinCluster(cls, shapeNode):
		'''
		If this flag is set, only nodes whose historicallyInteresting attribute value is not 
		less than the value will be listed. The historicallyInteresting attribute is 0 on nodes 
		which are not of interest to non-programmers. 1 for the TDs, 2 for the users.
		'''
		history = cmds.listHistory(shapeNode,pdo=True,il=2)
		if not history:
			return None
		for x in history:
			if cmds.nodeType(x) == 'skinCluster':
				skins = x
		if skins:
			return skins
		return None

	#constructor
	def __init__(self, shape = None):
		if not shape:
			try:
				shape = cmds.ls(sl=True)[0]
			except:
				raise RuntimeError('No Shape is selected')
		#convert selection to valid shape node 
		self.shape = getShape(shape)

		if not self.shape:
			raise RuntimeError('No shape connected to %s' % self.shape)
		#get the skinCluster node attached to the shape
		self.node = SkinCluster.getSkinCluster(self.shape)
		if not self.node:
			raise RuntimeError('No skinCluster attached to %s' %self.shape)
		#Get the skinCluster MObjet
		selectionList = OpenMaya.MSelectionList()
		selectionList.add(self.node)
		self.mObj_skinCluster = OpenMaya.MObject()
		selectionList.getDependNode(0, self.mObj_skinCluster)
		self.mfnSkinCluster = OpenMayaAnim.MFnSkinCluster(self.mObj_skinCluster)
		self.data = {
					#weights ----> dictionary
					'weights' : {},
					'blendWeights': [],
					'name' : self.node
					}

	def gatherData(self):
		dagPath, components = self.getGeomInfo()
		self.gatherInfluenceWeights(dagPath, components)
		self.gatherBlendWeights(dagPath, components)
		for attr in ['skinningMethod','normalizeWeights']:
			self.data[attr] = cmds.getAttr('%s.%s' %(self.node,attr))



	def getGeomInfo(self):
		fnSet = OpenMaya.MFnSet(self.mfnSkinCluster.deformerSet())
		memebers = OpenMaya.MSelectionList()
		fnSet.getMembers(memebers,False)
		dagPath = OpenMaya.MDagPath()
		components = OpenMaya.MObject()
		memebers.getDagPath(0, dagPath, components)
		return dagPath, components


	def gatherInfluenceWeights(self, dagPath, component):
		weights = OpenMaya.MDoubleArray()
		util =OpenMaya.MScriptUtil()
		util.createFromInt(0)
		pUInt = util.asUintPtr()
		self.mfnSkinCluster.getWeights(dagPath, component, weights, pUInt)
		# query numeber of influences
		mDagPathArray = OpenMaya.MDagPathArray()
		numInfuluenceObj = self.mfnSkinCluster.influenceObjects(mDagPathArray)
		numWeights = weights.length()
		numComponentsPerInfluence = numWeights / numInfuluenceObj
		for i in xrange(numInfuluenceObj):
			tempList = []
			InfluenceName = mDagPathArray[i].partialPathName()
			InfluenceNWithoutNameSpace = SkinCluster.removeNameSpace(InfluenceName) 
			#we need to store the weight by inflence
			for j in xrange(numComponentsPerInfluence):
				tempList.append(weights[i + numInfuluenceObj * j])
			self.data['weights'][InfluenceName] = tempList


	def gatherBlendWeights(self, dagPath, component):
		blendWeights = OpenMaya.MDoubleArray()
		self.mfnSkinCluster.getBlendWeights(dagPath, component, blendWeights)
		for i in xrange (blendWeights.length()):
			self.data['blendWeights'].append(blendWeights[i])

	def setData(self, data):
		'''set the data and store them in the Maya skinCluster node
		'''
		self.data = data
		dagPath, components = self.getGeomInfo()
		self.setInfluentsWeights(dagPath, components)
		self.setBlendWeights(dagPath, components)

		for attr in ['skinningMethod','normalizeWeights']:
			cmds.setAttr('%s.%s' %(self.node, attr), self.data[attr])

	def setInfluentsWeights(self, dagPath, components):

		mDagPathArray =OpenMaya.MDagPathArray()
		numInfuluenceObj = self.mfnSkinCluster.influenceObjects(mDagPathArray)
		numComponentsPerInfluence = len(self.data['blendWeights'])
		weights = OpenMaya.MDoubleArray()
		weights.setLength(numInfuluenceObj*numComponentsPerInfluence)
		#assign weight based on imported data
		weightsDictionary = self.data['weights']
		#print weightsDictionary.keys()
		'''
		for i in xrange(numComponentsPerInfluence):
			for j in xrange(numInfuluenceObj):
				#get influencers from skinCluster
				InfulenceName = mDagPathArray[j].partialPathName()
				infulenceWithoutNameSpace = SkinCluster.removeNameSpace(InfulenceName)
				#if skincluster already exsits:
				#check influencers between imported data and exsiting data
				if infulenceWithoutNameSpace == SkinCluster.removeNameSpace(weightsDictionary.keys()[j]):
					weights.append(weightsDictionary[infulenceWithoutNameSpace][i])
				#noMatchJoints.remove(infulenceWithoutNameSpace)
		'''
		for influencer, inflenceWeights in weightsDictionary.items():
			for i in xrange(numInfuluenceObj):
				InfluenceName = mDagPathArray[i].partialPathName()
				InfluenceWithoutNameSpace = SkinCluster.removeNameSpace(InfluenceName)
				if influencer == InfluenceWithoutNameSpace:
					for j in xrange(numComponentsPerInfluence):
						weights.set(inflenceWeights[j],numInfuluenceObj * j+i)
					break

		influenceIndices = OpenMaya.MIntArray()
		for i in xrange(numInfuluenceObj):
			influenceIndices.append(i)
		self.mfnSkinCluster.setWeights(dagPath, components, influenceIndices, weights, False)

	def setBlendWeights(self, dagPath, components):
		blendWeights = OpenMaya.MDoubleArray()
		numBlendWeights = len(self.data['blendWeights'])
		for i in range(numBlendWeights):
			blendWeights.append(self.data['blendWeights'][i])
		self.mfnSkinCluster.setBlendWeights(dagPath, components, blendWeights)


	def exportSkin(self, filePath = None): 
		#export skin data to disk
		if not filePath:
			defaultDir = cmds.workspace(q=True, rd=True)
			filePath = cmds.fileDialog2(ds=2, cap='Export Skin Data', dir=defaultDir, 
										okc='Export',ff = 'skin Files(*%s)' %SkinCluster.kFileExtension)
		if not filePath:
			return
		filePath = str(filePath[0])

		if not filePath.endswith(SkinCluster.kFileExtension):
			filePath += SkinCluster.kFileExtension
		self.gatherData()
		fh = open(filePath, 'wb')
		cPickle.dump(self.data, fh, cPickle.HIGHEST_PROTOCOL)
		fh.close()
		print 'Exported skinCluster (%d influences, %d vertices) %s' %(len(self.data['weights'].keys()),
																	   len(self.data['blendWeights']),
																	   filePath)

class MainSkinUI(object):
	MainWindowID = 'MainUI'
	RemapWindowID = 'RemapUI'
	def __init__(self): 
		self.InfluenceMapping={}

	@classmethod
	def showMainWindow(cls):
		if (cmds.window(MainSkinUI.MainWindowID,ex=True)):
			cmds.deleteUI(MainSkinUI.MainWindowID, wnd=True)
		cmds.window(MainSkinUI.MainWindowID, w=300,h=150,title='Vertex Based Skin Weight IO')
		cmds.columnLayout(w=300,h=150,rs=10)
		cmds.columnLayout(cat=['left',25])
		cmds.text(l='Compared to UV based skin exporter, the tool\n exports skin weight'\
					' based on vertex ID', w=250,h=40,al='center')
		cmds.setParent('..')
		cmds.separator(w=300,st='in')
		cmds.columnLayout(cat =['left',50],rs=5)
		cmds.button('Export Skin Weight Data',w=200,c=SkinCluster.exportData)
		cmds.button('Import Skin Weight Data',w=200,c=SkinCluster.importData)
		cmds.showWindow(MainSkinUI.MainWindowID)


	def remappingWindow(self,exsitingData,importedData):
		#if (cmds.window(MainSkinUI.RemapWindowID,ex=True)):
			#cmds.deleteUI(MainSkinUI.RemapWindowID, wnd=True)
		#cmds.window(MainSkinUI.RemapWindowID,w=500,h=340,title='Influence Remapping Dialog')
		formLayout=cmds.setParent(q=True)
		cmds.formLayout(formLayout,e=True,w=500,h=340)
		mainColumnLayout = cmds.columnLayout(w=500,h=340)
		cmds.columnLayout(h=5)
		cmds.setParent('..')
		cmds.columnLayout(cat=['left',25])
		cmds.text(l='The following influences hace no corresponding influence from the imported weight\n'\
					' data. You can remap the influences or skip them',al='left', w=450,h=40)
		cmds.setParent('..')
		cmds.separator(w=500, st='in')
		formLayout = cmds.formLayout()
		exsitingInfluences = cmds.columnLayout()
		cmds.frameLayout(l='Exsiting Influences:')
		self.exsitingInfluencesBox = cmds.textScrollList(w=230,h=230)
		cmds.setParent('..')
		cmds.setParent('..')
		importedInfluences = cmds.columnLayout()
		cmds.frameLayout(l='Imported Influences:')
		self.importedInfluencesLayout = cmds.columnLayout(w=230,h=230)
		cmds.columnLayout(h=5)
		cmds.setParent('..')
		#self.importedInfluencesLayout = cmds.columnLayout(cat=['left',40])
		cmds.formLayout(formLayout,e=True,af=[(exsitingInfluences,'left',10)],ac=[(importedInfluences,'left',10,exsitingInfluences)])
		cmds.setParent(mainColumnLayout)
		cmds.columnLayout(h=5)
		cmds.setParent('..')
		cmds.columnLayout(cat=['left',150])
		cmds.button(l='Import Remapped Skin Weight', w=200, c=self.passRemappingData)
		self.setInfluenceDialog(exsitingData,importedData)
		#cmds.showWindow(MainSkinUI.RemapWindowID)

	def showModalDialog(self,exsitingData,importedData):
		cmds.layoutDialog(ui=partial(self.remappingWindow,exsitingData,importedData))


	def setInfluenceDialog(self, exsitingData, importedData):
		#ascending order
		exsitingData.sort()
		cmds.textScrollList(self.exsitingInfluencesBox,a=exsitingData,e=True)
		for item in importedData:
			cmds.rowLayout(p=self.importedInfluencesLayout,nc=3,h=30,cat=[(1,'left',15),(2,'both',10),(3,'right',15)])
			self.source = cmds.textField(tx=item,ed=False,w=60,h=20) #cmds.text(l=item,al='left')
			button = cmds.button(l='remap',w=50,h=20)
			self.destination = cmds.textField(tx='',ed=False,w=60,h=20) #cmds.text(l='')
			cmds.button(button,e=True,c=partial(self.setDestInfluences,item,self.destination))
			cmds.setParent('..')
			cmds.separator(w=230,st='in')


	def setDestInfluences(self, importedData, destinationTxtBox ,*arg):
		destinationInfluence = cmds.textField(destinationTxtBox,tx=True,q=True)
		if not destinationInfluence:
			existingData =cmds.textScrollList(self.exsitingInfluencesBox,q=True,si=True)
			try:
				cmds.textField(destinationTxtBox,tx=existingData[0],e=True)
				#convert the unicode to str
				self.InfluenceMapping[importedData] = str(existingData[0])
				cmds.textScrollList(self.exsitingInfluencesBox,e=True,ri = existingData)
			except:
				pass
		else:
			cmds.textScrollList(self.exsitingInfluencesBox,e=True,a=destinationInfluence)
			cmds.textField(destinationTxtBox,e=True,tx='')

	def passRemappingData(self, *arg):
		#if (cmds.window(MainSkinUI.RemapWindowID,ex=True)):
			#cmds.deleteUI(MainSkinUI.RemapWindowID, wnd=True)
		cmds.layoutDialog(dis='Dismiss')



MainSkinUI.showMainWindow()
#mainWindow = MainSkinUI()
#mainWindow.showMainWindow()
#mainWindow.showRemappingWindow()
#exsitingData = ['4','2','3','1']
#importedData = ['2000000000000','3','4']
#mainWindow.setInfluenceDialog(exsitingData,importedData)
