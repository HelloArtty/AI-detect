import psycopg2
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
import os
import json
import dotenv
import openai
import uvicorn
import cloudinary
import cloudinary.uploader
from fastapi.middleware.cors import CORSMiddleware
from psycopg2.extras import RealDictCursor

# โหลด ENV
dotenv.load_dotenv()

# ตั้งค่า API Key ของ OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")
DATABASE_URL = os.getenv("DATABASE_URL")

app = FastAPI()

origins = [
    "http://localhost:3000",
    "https://kidney-care.vercel.app"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class CloudinaryManager:
    @staticmethod
    def upload_to_cloudinary(file: UploadFile):
        # ตั้งค่าการเชื่อมต่อ Cloudinary
        cloudinary.config(
            cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
            api_key=os.getenv("CLOUDINARY_API_KEY"),
            api_secret=os.getenv("CLOUDINARY_API_SECRET")
        )
        # อัปโหลดไฟล์ไปยัง Cloudinary
        response = cloudinary.uploader.upload(file.file, resource_type="image")
        return response.get("secure_url")

    @staticmethod
    def delete_from_cloudinary(public_url: str):
        # ดึง public_id จาก URL
        public_id = public_url.split("/")[-1].split(".")[0]
        cloudinary.uploader.destroy(public_id)

class DatabaseManager:
    @staticmethod
    def get_db_connection():
        try:
            connection = psycopg2.connect(DATABASE_URL, sslmode='require')
            connection.autocommit = True
            # ตรวจสอบการเชื่อมต่อ
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            if result[0] != 1:
                raise Exception("Database connection failed")
            cursor.close()
            print("✅ Database connection established successfully")
            return connection
        except Exception as e:
            print(f"❌ Error connecting to the database: {e}")
            raise HTTPException(status_code=500, detail="Database connection error")

class FoodDetection:
    @staticmethod
    async def analyze_food(file: UploadFile):
        image_url = CloudinaryManager.upload_to_cloudinary(file)
        prompt = '''
            จากภาพนี้ ช่วยวิเคราะห์และบอกชื่ออาหารที่ปรากฏอยู่ในภาพนี้ให้แม่นยำที่สุด
            - ตอบเฉพาะชื่ออาหารที่มั่นใจที่สุดว่าคืออะไร
            - เขียนชื่ออาหารเป็นภาษาไทยในรูปแบบ array เช่น ["ข้าวมันไก่"]
            - ไม่ต้องบอกส่วนผสมของอาหาร เช่น "ข้าวผัดหมู", "ต้มยำกุ้ง" หรือ "แกงเขียวหวานไก่" ให้ตอลแค่ "ต้มยำ" , "แกงเขียวหวาน"
            - ไม่ต้องระบุเครื่องเคียง หรือคำว่า 'ในจานมี' หรือ 'มีส่วนผสม'
            - เลือกแค่ 1 ชื่ออาหารที่เด่นและมั่นใจที่สุดจากภาพนี้เท่านั้น
            - หากไม่ใช่ภาพอาหารให้ตอบว่า "ไม่สามารถตรวจภาพที่ไม่ใช่อาหารได้"
        '''

        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "คุณเป็นผู้ช่วย AI ที่ช่วยตรวจจับอาหารจากภาพ"},
                    {"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": { "url": image_url }}
                    ]}
                ],
                max_tokens=100,
            )
            ai_response = response.choices[0].message.content
            cleaned_response = ai_response.replace("```json", "").replace("```", "").strip()

            try:
                cleaned = json.loads(cleaned_response)
                food_name = cleaned[0] if isinstance(cleaned, list) and cleaned else None
                recipes_ai = [{"recipes_id": 0, "recipes_name": food_name}] if food_name else []
                if not food_name:
                    return JSONResponse(content={"error": "รูปแบบข้อมูลไม่ถูกต้อง"}, status_code=400)
            except json.JSONDecodeError:
                return JSONResponse(content={"error": "ไม่สามารถแปลง JSON ได้"}, status_code=400)

            conn = DatabaseManager.get_db_connection()
            try:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT recipe_id, recipe_name FROM recipes WHERE recipe_name ILIKE %s",
                    ('%' + food_name + '%',)
                )
                rows = cursor.fetchall()
                matched = [{"recipes_id": row[0], "recipes_name": row[1]} for row in rows] if rows else []
                return {"recipes_ai": recipes_ai, "recipes": matched or "ไม่พบเมนูอาหารที่ตรงกับชื่ออาหารที่ระบุ"}
            finally:
                cursor.close()
                conn.close()
        finally:
            CloudinaryManager.delete_from_cloudinary(image_url)

class IngredientsDetection:
    @staticmethod
    async def analyze_ingredients(file: UploadFile):
        image_url = CloudinaryManager.upload_to_cloudinary(file)
        prompt = '''
                บอกชื่อวัตถุดิบที่ปรากฏในภาพเป็นภาษาไทยและภาษาอังกฤษในรูปแบบ array เช่น [["ข้าว", "ปลา"], ["rice", "fish"]]
                ### ข้อกำหนด:
                1. ไม่ต้องระบุจำนวน เช่น ถ้ามีไข่ 3 ฟอง ให้ใส่เพียง "ไข่" (egg)
                2. ไม่ต้องระบุชนิด เช่น "ข้าวหอมมะลิ" หรือ "ข้าวกล้อง" ให้ใส่เพียง "ข้าว" (rice)
                3. เนื้อสัตว์ให้ใส่เฉพาะชื่อ เช่น "ไก่" ไม่ต้องใส่ "เนื้อไก่"
                - **ยกเว้น** เนื้อวัว ให้ใส่เป็น "เนื้อวัว" (beef) และเนื้อสัตว์ชนิดพิเศษ เช่น "เป็ด" (duck)
                4. ผักและผลไม้ให้ใส่ชื่อเฉพาะ เช่น "แตงโม" ไม่ต้องใส่ "ผลแตงโม"
                5. เครื่องปรุงรส เช่น "น้ำปลา", "ซีอิ๊ว" ให้ใส่ตามชื่อปกติ
                6. ถ้าเป็นอาหารที่มีส่วนผสมหลายอย่าง ให้แยกออกเป็นวัตถุดิบเดี่ยว เช่น "ข้าวผัด" ต้องแยกเป็น ["ข้าว", "ไข่", "น้ำมัน", "ซีอิ๊ว"]
                7. ใส่ชื่อภาษาไทยก่อนแล้วตามด้วยภาษาอังกฤษ เช่น [["ข้าว", "ไข่"], ["rice", "egg"]]
                8. หากตรวจไม่พบวัตถุดิบ ให้ส่งคืนค่าเป็น `[["ไม่สามารถตรวจจับได้"], ["unable to detect"]]`
                9. วัตถุดิบที่ผ่านการแปรรูปเล็กน้อย เช่น "หมูสับ" ให้ใส่เป็น "หมู" (pork) แต่ถ้าเป็นอาหารแปรรูป เช่น "ไส้กรอก" ให้คงชื่อเดิม
                10. น้ำซุป เช่น "น้ำซุปกระดูกหมู" ให้แยกเป็น ["หมู", "น้ำซุป"]
                11. วัตถุดิบแห้ง เช่น "กุ้งแห้ง" ให้ใส่เป็น "กุ้ง" (shrimp)
                12. แยกประเภทของถั่ว เช่น "ถั่วลิสง" (peanut), "อัลมอนด์" (almond)
                13. แยกวัตถุดิบหลักออกจากเครื่องปรุง เช่น "เกลือ", "น้ำตาล" ให้ใส่ตามชื่อ
                14. วัตถุดิบที่ถูกบด เช่น "กระเทียมบด" ให้ใส่เป็น "กระเทียม" (garlic)
                15. วัตถุดิบหายาก เช่น "ใบมะกรูด" ให้ใช้ชื่อเดิม (kaffir lime leaf)
                16. เส้นอาหาร เช่น "เส้นก๋วยเตี๋ยว" ให้ใส่เป็น "เส้น" (noodles) และ "สปาเกตตี" เป็น "พาสต้า" (pasta)
                17. หากเป็นวัตถุดิบเดียวกันแต่ต่างรูปแบบ เช่น "ไข่ต้ม" หรือ "ไข่ดาว" ให้ใส่เป็น "ไข่" (egg)
                18. ใช้คำทั่วไปเมื่อมีหลายชื่อ เช่น "ต้นหอม" แทน "หอมซอย"
                19. หากไม่สามารถระบุวัตถุดิบได้อย่างชัดเจน ให้คืนค่า `[["ไม่สามารถตรวจจับได้"], ["unable to detect"]]`
                20. หากไม่ใช่รูปภาพที่เป็นวัตถุดิบให้คืนค่า `[["ไม่สามารถตรวจจับรูปที่ไม่ใช่อาหารได้"],["unable to detec"]]
            '''

        try:
            # เรียกใช้ OpenAI API
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "คุณเป็นผู้ช่วย AI ที่ช่วยตรวจจับวัตถุดิบจากภาพอาหาร"},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {"type": "image_url", "image_url": {"url": image_url}}
                        ],
                    },
                ],
                max_tokens=200,
            )
            # ดึงข้อความจาก AI และแปลงเป็น JSON
            ai_response = response["choices"][0]["message"]["content"]
            # print(ai_response)
            cleaned_response = ai_response.replace("```json", "").replace("```", "").strip()
            # print(cleaned_response)
            try:
                cleaned = json.loads(cleaned_response)  # แปลงข้อความ JSON เป็น List
                if len(cleaned) == 2 and len(cleaned[0]) == len(cleaned[1]):  # ตรวจสอบข้อมูล
                    ingredients_dict = [
                        {
                            "id": index,
                            "ingredient_name": th_word,
                            "ingredient_name_eng": en_word
                        } for index, (th_word, en_word) in enumerate(zip(cleaned[0], cleaned[1]))
                    ]
                    # เชื่อมต่อฐานข้อมูล
                    conn = DatabaseManager.get_db_connection()
                    cursor = conn.cursor(cursor_factory=RealDictCursor)
                    try:
                        cursor = conn.cursor()
                        ingredients = []

                        for th_word in cleaned[0]:
                            cursor.execute(
                                "SELECT ingredient_id, ingredient_name, ingredient_name_eng FROM ingredients WHERE ingredient_name LIKE %s",
                                ('%' + th_word + '%',)
                            )
                            rows = cursor.fetchall()
                            if rows:
                                ingredients.extend([
                                    {"id": row[0], "ingredient_name": row[1], "ingredient_name_eng": row[2]} for row in rows
                                ])

                        if ingredients:
                            return JSONResponse(content={"ingredients_ai":ingredients_dict,"ingredients": ingredients}, status_code=200)
                        else:
                            return JSONResponse(content={"error": "ไม่พบวัตถุดิบที่ตรงกับชื่อที่ระบุ"}, status_code=400)
                    finally:
                        cursor.close()
                        conn.close()
                else:
                    return JSONResponse(content={"error": "รูปแบบข้อมูลไม่ถูกต้อง"}, status_code=400)
            except json.JSONDecodeError:
                return JSONResponse(content={"error": "ไม่สามารถแปลง JSON ได้"}, status_code=400)
        finally:
            CloudinaryManager.delete_from_cloudinary(image_url)

@app.post("/detect-foods/")
async def detect_foods(file: UploadFile = File(...)):
    return await FoodDetection.analyze_food(file)

@app.post("/detect-ingredients/")
async def detect_ingredients(file: UploadFile = File(...)):
    return await IngredientsDetection.analyze_ingredients(file)


@app.get("/")
def read_root():
    return {"message": "API is running"}


# สร้างฟังก์ชันสำหรับรัน API ด้วย Uvicorn
if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)